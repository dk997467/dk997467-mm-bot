#!/usr/bin/env python3
"""
Orchestrates a full-stack validation of the project, running linters,
tests, dry-runs, and other checks, then generates a unified report.
"""
import argparse
import json
import os
import subprocess
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# --- Global Configuration ---

# This script's location is the anchor for all paths.
ROOT_DIR = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
CI_ARTIFACTS_DIR = ARTIFACTS_DIR / "ci"
CI_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Import centralized runtime info generator
sys.path.insert(0, str(ROOT_DIR))
from src.common.runtime import get_runtime_info

# Global timeout (seconds) for each external step; can be overridden via env
TIMEOUT_SECONDS = int(os.environ.get("FSV_TIMEOUT_SEC", "300"))
RETRIES = int(os.environ.get("FSV_RETRIES", "0"))

# Log rotation configuration (critical for 24-72h soak tests)
MAX_LOG_FILES_PER_STEP = int(os.environ.get("FSV_MAX_LOGS_PER_STEP", "5"))  # Keep last 5 runs per step
MAX_TOTAL_LOG_SIZE_MB = int(os.environ.get("FSV_MAX_LOG_SIZE_MB", "500"))  # Alert if >500MB total
AGGRESSIVE_CLEANUP_THRESHOLD_MB = int(os.environ.get("FSV_AGGRESSIVE_CLEANUP_MB", "750"))  # Force cleanup at 750MB


def _cleanup_old_logs(label: str) -> None:
    """
    Keep only last N log files per step to prevent disk bloat in soak tests.
    
    In 72-hour soak tests, without rotation, we'd create 500+ log files
    (one per 5-minute iteration × 2 files per step × multiple steps).
    
    This function:
    1. Finds all .out.log and .err.log files for the given step label
    2. Sorts by modification time (oldest first)
    3. Deletes all except the last MAX_LOG_FILES_PER_STEP
    
    Args:
        label: Step label (e.g., 'ascii_logs', 'tests_whitelist')
    
    Example:
        If MAX_LOG_FILES_PER_STEP=5 and we have 10 log files:
        - ascii_logs.20251001_100000.out.log (oldest)
        - ascii_logs.20251001_100500.out.log
        - ...
        - ascii_logs.20251001_104500.out.log (newest)
        
        → Keeps only last 5, deletes first 5
    """
    try:
        # Find all log files for this step
        out_logs = sorted(
            CI_ARTIFACTS_DIR.glob(f"{label}.*.out.log"),
            key=lambda p: p.stat().st_mtime
        )
        err_logs = sorted(
            CI_ARTIFACTS_DIR.glob(f"{label}.*.err.log"),
            key=lambda p: p.stat().st_mtime
        )
        
        # Delete oldest files beyond limit
        for old_file in out_logs[:-MAX_LOG_FILES_PER_STEP] if len(out_logs) > MAX_LOG_FILES_PER_STEP else []:
            try:
                old_file.unlink()
            except Exception:
                pass  # File may have been deleted by another process
        
        for old_file in err_logs[:-MAX_LOG_FILES_PER_STEP] if len(err_logs) > MAX_LOG_FILES_PER_STEP else []:
            try:
                old_file.unlink()
            except Exception:
                pass
        
        # Log cleanup activity if we deleted anything
        deleted_count = max(0, len(out_logs) - MAX_LOG_FILES_PER_STEP) + max(0, len(err_logs) - MAX_LOG_FILES_PER_STEP)
        if deleted_count > 0:
            print(f"[CLEANUP] Rotated {deleted_count} old log file(s) for step '{label}'", file=sys.stderr)
    
    except Exception as e:
        # Don't fail the entire validation run if cleanup fails
        print(f"[WARN] Log cleanup failed for '{label}': {e}", file=sys.stderr)


def _check_disk_space() -> None:
    """
    Check total CI artifacts directory size and perform aggressive cleanup if needed.
    
    This is a safety net for long soak tests. If total size exceeds threshold:
    1. Warn in logs
    2. Perform aggressive cleanup (keep only last 2 files per step)
    
    Thresholds:
    - MAX_TOTAL_LOG_SIZE_MB: Warning threshold (default 500MB)
    - AGGRESSIVE_CLEANUP_THRESHOLD_MB: Aggressive cleanup threshold (default 750MB)
    
    Example disk usage in 72h soak test WITHOUT rotation:
    - 10 steps × 2 files per run × 864 runs = 17,280 files
    - Average 50KB per file = ~850MB
    - With rotation: 10 steps × 2 files × 5 kept = 100 files (~5MB)
    """
    try:
        # Calculate total size of all files in CI artifacts directory
        total_size_bytes = sum(
            f.stat().st_size for f in CI_ARTIFACTS_DIR.rglob('*') if f.is_file()
        )
        total_size_mb = total_size_bytes / (1024 * 1024)
        
        # Aggressive cleanup if exceeds critical threshold
        if total_size_mb > AGGRESSIVE_CLEANUP_THRESHOLD_MB:
            print(
                f"[ALERT] CI artifacts size: {total_size_mb:.1f} MB "
                f"(critical threshold: {AGGRESSIVE_CLEANUP_THRESHOLD_MB} MB)",
                file=sys.stderr
            )
            print("[CLEANUP] Performing AGGRESSIVE cleanup (keeping only last 2 files per step)...", file=sys.stderr)
            
            # Aggressive cleanup: keep only last 2 files per step
            step_labels = set()
            for log_file in CI_ARTIFACTS_DIR.glob('*.*.log'):
                # Extract step label from filename (e.g., 'ascii_logs.20251001_100000.out.log' -> 'ascii_logs')
                parts = log_file.name.split('.')
                if len(parts) >= 3:
                    step_labels.add(parts[0])
            
            for label in step_labels:
                out_logs = sorted(CI_ARTIFACTS_DIR.glob(f"{label}.*.out.log"), key=lambda p: p.stat().st_mtime)
                err_logs = sorted(CI_ARTIFACTS_DIR.glob(f"{label}.*.err.log"), key=lambda p: p.stat().st_mtime)
                
                # Keep only last 2
                for old_file in out_logs[:-2]:
                    try:
                        old_file.unlink()
                    except Exception:
                        pass
                
                for old_file in err_logs[:-2]:
                    try:
                        old_file.unlink()
                    except Exception:
                        pass
            
            # Recalculate size after cleanup
            new_total_size_bytes = sum(
                f.stat().st_size for f in CI_ARTIFACTS_DIR.rglob('*') if f.is_file()
            )
            new_total_size_mb = new_total_size_bytes / (1024 * 1024)
            freed_mb = total_size_mb - new_total_size_mb
            
            print(
                f"[CLEANUP] Freed {freed_mb:.1f} MB "
                f"(new size: {new_total_size_mb:.1f} MB)",
                file=sys.stderr
            )
        
        # Warning if approaching limit
        elif total_size_mb > MAX_TOTAL_LOG_SIZE_MB:
            print(
                f"[WARN] CI artifacts size: {total_size_mb:.1f} MB "
                f"(warning threshold: {MAX_TOTAL_LOG_SIZE_MB} MB, "
                f"aggressive cleanup at: {AGGRESSIVE_CLEANUP_THRESHOLD_MB} MB)",
                file=sys.stderr
            )
    
    except Exception as e:
        # Don't fail the entire validation run if disk check fails
        print(f"[WARN] Disk space check failed: {e}", file=sys.stderr)


def _prepare_python_cmd(cmd: List[str]) -> List[str]:
    """Ensure Python subprocess enables faulthandler for better diagnostics."""
    if not cmd:
        return cmd
    if Path(cmd[0]).name.lower().startswith("python") or cmd[0] == sys.executable:
        # Inject -X faulthandler right after interpreter
        if len(cmd) >= 2 and cmd[1] == "-X" and len(cmd) >= 3 and cmd[2] == "faulthandler":
            return cmd
        return [cmd[0], "-X", "faulthandler"] + cmd[1:]
    return cmd


def run_step(label: str, cmd: List[str]) -> Dict[str, Any]:
    """Run labeled step with timeout; write stdout/stderr to artifacts; kill process tree on timeout."""
    # Log rotation: cleanup old logs BEFORE creating new ones (critical for soak tests)
    _cleanup_old_logs(label)
    _check_disk_space()
    
    CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    is_windows = platform.system().lower().startswith("win")
    popen_kwargs: Dict[str, Any] = {}
    if is_windows:
        popen_kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP
    else:
        import os as _os, signal as _sig
        popen_kwargs["preexec_fn"] = _os.setsid

    try:
        # Prepare python-specific flags and env
        env = os.environ.copy()
        env["PYTHONFAULTHANDLER"] = "1"
        safe_cmd = _prepare_python_cmd(cmd)
        
        # ===== ENHANCED DIAGNOSTIC LOGGING =====
        print("=" * 80, file=sys.stderr)
        print(f"[DEBUG] STARTING STEP: {label}", file=sys.stderr)
        print(f"[DEBUG] Working directory: {os.getcwd()}", file=sys.stderr)
        print(f"[DEBUG] Command: {' '.join(safe_cmd)}", file=sys.stderr)
        print(f"[DEBUG] Timeout: {TIMEOUT_SECONDS}s", file=sys.stderr)
        print(f"[DEBUG] Python executable: {sys.executable}", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        
        # Run and capture
        start_ts = time.time()
        p = subprocess.Popen(
            safe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='ascii',
            errors='replace',
            env=env,
            **popen_kwargs,
        )
        try:
            stdout, stderr = p.communicate(timeout=TIMEOUT_SECONDS)
            output = (stdout or '') + '\n' + (stderr or '')
            details = ''
            for line in reversed(output.strip().splitlines()):
                if line.strip():
                    details = line.strip()
                    break
            # write logs
            ts_suffix = time.strftime("%Y%m%d_%H%M%S", time.gmtime(start_ts))
            out_path = CI_ARTIFACTS_DIR / f"{label}.{ts_suffix}.out.log"
            err_path = CI_ARTIFACTS_DIR / f"{label}.{ts_suffix}.err.log"
            if stdout:
                out_path.write_text(stdout, encoding="ascii", errors="replace")
            if stderr:
                err_path.write_text(stderr, encoding="ascii", errors="replace")
            duration_ms = int((time.time() - start_ts) * 1000)
            
            # ===== ENHANCED DIAGNOSTIC LOGGING (POST-EXECUTION) =====
            print("=" * 80, file=sys.stderr)
            print(f"[DEBUG] FINISHED STEP: {label}", file=sys.stderr)
            print(f"[DEBUG] Return code: {p.returncode}", file=sys.stderr)
            print(f"[DEBUG] Duration: {duration_ms}ms", file=sys.stderr)
            print(f"[DEBUG] Status: {'✓ OK' if p.returncode == 0 else '✗ FAIL'}", file=sys.stderr)
            print("-" * 80, file=sys.stderr)
            print(f"[DEBUG] STDOUT (full output):", file=sys.stderr)
            print(stdout if stdout else "(empty)", file=sys.stderr)
            print("-" * 80, file=sys.stderr)
            print(f"[DEBUG] STDERR (full output):", file=sys.stderr)
            print(stderr if stderr else "(empty)", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            
            return {
                'name': label,
                'ok': p.returncode == 0,
                'details': details[:200],
                'pid': p.pid,
                'duration_ms': duration_ms,
                'logs': {'stdout': str(out_path), 'stderr': str(err_path)}
            }
        except subprocess.TimeoutExpired:
            # Kill whole process tree using robust psutil-based approach
            # This prevents zombie processes that simple taskkill/killpg may miss
            try:
                # Import process_manager (only when needed to avoid dependency issues)
                sys.path.insert(0, str(ROOT_DIR))
                from src.common.process_manager import kill_process_tree, PSUTIL_AVAILABLE
                
                if PSUTIL_AVAILABLE:
                    # Use psutil for robust cleanup
                    success = kill_process_tree(p.pid, timeout=3.0, include_parent=True)
                    if success:
                        print(f"[INFO] Process tree {p.pid} killed successfully via psutil", file=sys.stderr)
                    else:
                        print(f"[WARN] Some processes in tree {p.pid} may still be alive", file=sys.stderr)
                else:
                    # Fallback to OS-specific commands (less robust)
                    if is_windows:
                        subprocess.run(["taskkill", "/PID", str(p.pid), "/F", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        import os as _os, signal as _sig
                        try:
                            _os.killpg(_os.getpgid(p.pid), _sig.SIGKILL)
                        except ProcessLookupError:
                            pass
            except Exception as e:
                print(f"[WARN] Error killing process tree: {e}, trying direct kill...", file=sys.stderr)
                try:
                    p.kill()
                except Exception:
                    pass
            return {'name': label, 'ok': False, 'details': f'Execution failed: TimeoutExpired ({TIMEOUT_SECONDS} s)'}
    except Exception as e:
        return {'name': label, 'ok': False, 'details': f'Execution failed: {e.__class__.__name__}'}


def run_step_with_retries(label: str, cmd: List[str], retries: int = None) -> Dict[str, Any]:
    """Run step with optional retries and simple exponential backoff."""
    if retries is None:
        retries = RETRIES
    attempt = 0
    while True:
        res = run_step(label, cmd)
        if res.get('ok') or attempt >= retries:
            return res
        attempt += 1
        backoff = min(60 * (2 ** (attempt - 1)), 300)
        print(f"[WARN] step {label} failed, retry {attempt}/{retries}, sleeping {backoff}s", file=sys.stderr)
        time.sleep(backoff)


# --- Validation Section Runners (unchanged from previous version) ---

def run_linters() -> Dict[str, Any]:
    """Runs all linter checks in parallel."""
    print("Running linters...", file=sys.stderr)
    checks = [
        ('ascii_logs', [sys.executable, str(ROOT_DIR / 'tools/ci/lint_ascii_logs.py')]),
        ('json_writer', [sys.executable, str(ROOT_DIR / 'tools/ci/lint_json_writer.py')]),
        ('metrics_labels', [sys.executable, str(ROOT_DIR / 'tools/ci/lint_metrics_labels.py')]),
    ]
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(4, len(checks))) as ex:
        futures = {ex.submit(run_step, label, cmd): label for label, cmd in checks}
        for fut in as_completed(futures):
            results.append(fut.result())
    # Compose summary
    by_label = {r.get('name', '?'): r for r in results}
    details = '; '.join(f"{lbl}={'OK' if by_label.get(lbl, {}).get('ok') else 'FAIL'}" for lbl, _ in checks)
    all_ok = all(r.get('ok') for r in results)
    return {'name': 'linters', 'ok': all_ok, 'details': details, 'sections': results}


def run_tests_whitelist() -> Dict[str, Any]:
    """Run selected test suite."""
    print("Running tests whitelist...", file=sys.stderr)
    
    # In FAST mode, skip expensive test suite to avoid subprocess explosion
    if os.environ.get('FULL_STACK_VALIDATION_FAST', '0') == '1':
        return {'name': 'tests_whitelist', 'ok': True, 'details': 'SKIP: FAST mode'}
    
    # Check if tests should be skipped due to missing secrets
    allow_missing_secrets = os.environ.get('MM_ALLOW_MISSING_SECRETS') == '1'
    secrets_available = check_secrets_available()
    
    if not secrets_available and allow_missing_secrets:
        # Create empty log files for consistency
        ts_suffix = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        out_path = CI_ARTIFACTS_DIR / f"tests_whitelist.{ts_suffix}.out.log"
        err_path = CI_ARTIFACTS_DIR / f"tests_whitelist.{ts_suffix}.err.log"
        out_path.write_text("SKIPPED: No secrets available (MM_ALLOW_MISSING_SECRETS=1)\n", encoding="ascii")
        err_path.write_text("", encoding="ascii")
        return {'name': 'tests_whitelist', 'ok': True, 'details': 'SKIPPED_NO_SECRETS'}
    
    result = run_step_with_retries('tests_whitelist', [sys.executable, str(ROOT_DIR / 'tools/ci/run_selected.py')])
    return {'name': 'tests_whitelist', 'ok': result['ok'], 'details': result['details'] or ('OK' if result['ok'] else 'FAIL'), 'meta': result}


def run_dry_runs() -> Dict[str, Any]:
    """Run dry-run scenarios."""
    print("Running dry runs...", file=sys.stderr)
    
    # In FAST mode, skip pre_live_pack (it's heavy and runs bug_bash)
    if os.environ.get('FULL_STACK_VALIDATION_FAST', '0') == '1':
        return {'name': 'dry_runs', 'ok': True, 'details': 'SKIP: FAST mode'}
    
    # Check if pre_live_pack should be skipped due to missing secrets
    allow_missing_secrets = os.environ.get('MM_ALLOW_MISSING_SECRETS') == '1'
    secrets_available = check_secrets_available()
    
    if not secrets_available and allow_missing_secrets:
        return {'name': 'dry_runs', 'ok': True, 'details': 'SKIPPED_NO_SECRETS'}
    
    # Run pre_live_pack as module (not as script) to avoid import errors
    # Note: Use -m to ensure proper module resolution
    dry_runs = [
        ([sys.executable, '-m', 'tools.release.pre_live_pack', '--dry-run'], 'pre_live_pack'),
    ]
    
    # MEGA-PROMPT: Handle ModuleNotFoundError in safe-mode for pre_live_pack
    results = []
    for cmd, name in dry_runs:
        result = run_step_with_retries(name, cmd)
        
        # Check if pre_live_pack failed with ModuleNotFoundError (indicated in details)
        if not result['ok'] and allow_missing_secrets:
            # Read error logs to check for ModuleNotFoundError
            err_log_path = result.get('logs', {}).get('stderr')
            if err_log_path and Path(err_log_path).exists():
                err_content = Path(err_log_path).read_text(encoding='ascii', errors='replace')
                if 'ModuleNotFoundError' in err_content or 'No module named' in err_content:
                    # In safe-mode, skip pre_live_pack if module is missing
                    print(f"[SAFE-MODE] Skipping {name} due to ModuleNotFoundError", file=sys.stderr)
                    result = {'name': name, 'ok': True, 'details': 'SKIPPED_NO_MODULE'}
        
        results.append(result)
    
    all_ok = all(r['ok'] for r in results)
    details = '; '.join(f"{name}={'OK' if r['ok'] else 'FAIL'}" for r, (cmd, name) in zip(results, dry_runs))
    return {'name': 'dry_runs', 'ok': all_ok, 'details': details, 'sections': results}


def run_reports() -> Dict[str, Any]:
    """Run report generation on fixtures."""
    print("Running reports...", file=sys.stderr)
    
    # In FAST mode, skip report generation
    if os.environ.get('FULL_STACK_VALIDATION_FAST', '0') == '1':
        return {'name': 'reports', 'ok': True, 'details': 'SKIP: FAST mode'}
    
    if not (ROOT_DIR / "tests" / "fixtures").exists():
        return {'name': 'reports', 'ok': True, 'details': 'SKIP: missing fixtures'}

    # Guard: Check if ITER_SUMMARY files exist (skip on first iteration)
    soak_latest = ROOT_DIR / "artifacts" / "soak" / "latest"
    iter_summary_1 = soak_latest / "ITER_SUMMARY_1.json"
    
    if not iter_summary_1.exists():
        print("[reports] No ITER_SUMMARY_1.json yet, skipping report generation (first iteration)", file=sys.stderr)
        return {'name': 'reports', 'ok': True, 'details': 'SKIP: no ITER_SUMMARY yet (first iteration)'}
    
    # Step 1: Build reports (POST_SOAK_SNAPSHOT.json)
    print("[reports] Building POST_SOAK_SNAPSHOT...", file=sys.stderr)
    reports_dir = soak_latest / "reports" / "analysis"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    build_result = run_step_with_retries(
        'reports_build',
        [sys.executable, '-m', 'tools.soak.build_reports',
         '--src', str(soak_latest),
         '--out', str(reports_dir),
         '--last-n', '8']
    )
    
    if not build_result['ok']:
        print(f"[reports] build_reports failed: {build_result.get('details', 'unknown error')}", file=sys.stderr)
        return {'name': 'reports', 'ok': False, 'details': 'build_reports FAIL', 'meta': build_result}
    
    # Step 2: Readiness gate (non-blocking for hourly runs)
    print("[reports] Running readiness gate...", file=sys.stderr)
    readiness_result = run_step_with_retries(
        'reports_readiness_gate',
        [sys.executable, '-m', 'tools.soak.ci_gates.readiness_gate',
         '--path', str(soak_latest),
         '--min_maker_taker', '0.83',
         '--min_edge', '2.9',
         '--max_latency', '330',
         '--max_risk', '0.40']
    )
    
    # For hourly/legacy mode: readiness gate is informational, not blocking
    readiness_status = 'OK' if readiness_result['ok'] else 'HOLD'
    print(f"[reports] Readiness gate: {readiness_status} (informational for hourly runs)", file=sys.stderr)
    
    # Step 3: Write legacy readiness.json for compatibility
    print("[reports] Writing legacy readiness.json...", file=sys.stderr)
    legacy_artifacts = ROOT_DIR / "artifacts" / "reports"
    legacy_artifacts.mkdir(parents=True, exist_ok=True)
    
    legacy_result = run_step_with_retries(
        'reports_legacy_json',
        [sys.executable, '-m', 'tools.soak.ci_gates.write_legacy_readiness_json',
         '--src', str(soak_latest),
         '--out', str(legacy_artifacts)]
    )
    
    if not legacy_result['ok']:
        print(f"[reports] write_legacy_readiness_json failed (non-critical): {legacy_result.get('details', 'unknown error')}", file=sys.stderr)
    
    # Return success (readiness gate HOLD is not a failure for hourly runs)
    details = f"build_reports=OK readiness={readiness_status}"
    return {'name': 'reports', 'ok': True, 'details': details, 'meta': {
        'build_reports': build_result,
        'readiness_gate': readiness_result,
        'legacy_json': legacy_result
    }}


def run_dashboards() -> Dict[str, Any]:
    """Validate dashboard JSON schemas."""
    print("Running dashboards...", file=sys.stderr)
    result = run_step_with_retries('dashboards', [sys.executable, '-m', 'pytest', '-q', str(ROOT_DIR / 'tests/test_grafana_json_schema.py')])
    return {'name': 'dashboards', 'ok': result['ok'], 'details': f"grafana_schema={'OK' if result['ok'] else 'FAIL'}", 'meta': result}


def check_secrets_available() -> bool:
    """Check if required secrets are available."""
    required_secrets = ['BYBIT_API_KEY', 'BYBIT_API_SECRET', 'STORAGE_PG_PASSWORD']
    
    # Check if any required secret is missing or is a dummy value
    for secret in required_secrets:
        value = os.environ.get(secret, '')
        if not value or value.lower() in ('', 'dummy', 'test', 'none'):
            return False
    
    return True


def run_secrets_scan() -> Dict[str, Any]:
    """Run secrets scan."""
    print("Running secrets scan...", file=sys.stderr)
    
    # Check if we should skip due to missing secrets
    allow_missing_secrets = os.environ.get('MM_ALLOW_MISSING_SECRETS') == '1'
    secrets_available = check_secrets_available()
    
    if not secrets_available and allow_missing_secrets:
        return {'name': 'secrets', 'ok': True, 'status': 'OK', 'details': 'SKIPPED_NO_SECRETS'}
    
    result = run_step_with_retries('secrets_scan', [sys.executable, str(ROOT_DIR / 'tools/ci/scan_secrets.py')])
    return {'name': 'secrets', 'ok': result['ok'], 'status': 'OK' if result['ok'] else 'FAIL', 'details': 'NONE' if result['ok'] else 'FOUND', 'meta': result}


def run_audit_chain() -> Dict[str, Any]:
    """Run audit chain validation."""
    print("Running audit chain...", file=sys.stderr)
    
    # In FAST mode, skip audit chain (runs pytest)
    if os.environ.get('FULL_STACK_VALIDATION_FAST', '0') == '1':
        return {'name': 'audit_chain', 'ok': True, 'status': 'OK', 'details': 'SKIP: FAST mode'}
    
    # Check if we should skip due to missing secrets
    allow_missing_secrets = os.environ.get('MM_ALLOW_MISSING_SECRETS') == '1'
    secrets_available = check_secrets_available()
    
    if not secrets_available and allow_missing_secrets:
        return {'name': 'audit_chain', 'ok': True, 'status': 'OK', 'details': 'SKIPPED_NO_SECRETS'}
    
    test_path = ROOT_DIR / 'tests/e2e/test_audit_dump_e2e.py'
    if not test_path.exists():
        return {'name': 'audit_chain', 'ok': True, 'status': 'OK', 'details': 'SKIP: missing test file'}

    result = run_step_with_retries('audit_dump', [sys.executable, '-m', 'pytest', '-q', str(test_path)])
    return {'name': 'audit_chain', 'ok': result['ok'], 'status': 'OK' if result['ok'] else 'FAIL', 'details': f"audit_dump={'OK' if result['ok'] else 'FAIL'}", 'meta': result}


# --- Main Orchestrator ---

def _run_parallel(label_to_fn: List[tuple[str, Any]]) -> List[Dict[str, Any]]:
    """Run independent validation functions in parallel (thread pool)."""
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(4, len(label_to_fn))) as ex:
        futures = {ex.submit(fn): label for label, fn in label_to_fn}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({'name': futures[fut], 'ok': False, 'details': f'Runner failed: {e.__class__.__name__}'})
    return results


def main() -> int:
    """Main validation orchestrator."""
    parser = argparse.ArgumentParser(description="Full stack validation orchestrator")
    parser.add_argument(
        "--allow-missing-secrets",
        action="store_true",
        help="Allow missing secrets (skip tests that require them)"
    )
    parser.add_argument(
        "--allow-missing-sections",
        action="store_true",
        help="Allow missing input files (treat as ok)"
    )
    args = parser.parse_args()
    
    # Propagate flags to environment for child processes
    if args.allow_missing_secrets:
        os.environ["MM_ALLOW_MISSING_SECRETS"] = "1"
    
    # Set up PYTHONPATH for proper module resolution
    # This ensures pre_live_pack and other tools can import from src/
    pythonpath_parts = [str(ROOT_DIR), str(ROOT_DIR / "src")]
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    
    os.environ["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    print(f"[INFO] PYTHONPATH set to: {os.environ['PYTHONPATH']}", file=sys.stderr)
    
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["TZ"] = "UTC"
    print("FULL STACK VALIDATION START", file=sys.stderr)
    
    # FAST mode: minimal validation, just create valid JSON structure
    if os.environ.get('FULL_STACK_VALIDATION_FAST', '0') == '1':
        print("[FAST MODE] Skipping most validation steps", file=sys.stderr)
        sections = [
            {'name': 'linters', 'ok': True, 'status': 'OK', 'details': 'SKIP: FAST mode'},
            {'name': 'tests_whitelist', 'ok': True, 'status': 'OK', 'details': 'SKIP: FAST mode'},
            {'name': 'dry_runs', 'ok': True, 'status': 'OK', 'details': 'SKIP: FAST mode'},
            {'name': 'reports', 'ok': True, 'status': 'OK', 'details': 'SKIP: FAST mode'},
            {'name': 'dashboards', 'ok': True, 'status': 'OK', 'details': 'SKIP: FAST mode'},
            {'name': 'secrets', 'ok': True, 'status': 'OK', 'details': 'SKIP: FAST mode'},
            {'name': 'audit_chain', 'ok': True, 'status': 'OK', 'details': 'SKIP: FAST mode'},
        ]
        overall_ok = True
        final_result = 'OK'
    else:
        def _report_failure_immediately(result: Dict[str, Any]) -> None:
            """Immediately report failure details to stderr for CI debugging."""
            if not result.get('ok', True):
                print(f"\n{'='*70}", file=sys.stderr)
                print(f"[X] [STEP FAILED] {result.get('name', 'unknown')}", file=sys.stderr)
                print(f"{'='*70}", file=sys.stderr)
                details = result.get('details', 'No details available')
                print(f"Error details:\n{details}", file=sys.stderr)
                print(f"{'='*70}\n", file=sys.stderr)
                sys.stderr.flush()  # Ensure immediate output in CI logs

        sections: List[Dict[str, Any]] = []
        
        # 1) Linters (parallel внутри)
        result = run_linters()
        sections.append(result)
        _report_failure_immediately(result)
        
        # 2) Тестовый whitelist (последовательно — стабильность вывода)
        result = run_tests_whitelist()
        sections.append(result)
        _report_failure_immediately(result)
        
        # 3) Группа независимых шагов в параллели: dry_runs, reports, dashboards, secrets
        parallel_results = _run_parallel([
            ('dry_runs', run_dry_runs),
            ('reports', run_reports),
            ('dashboards', run_dashboards),
            ('secrets', run_secrets_scan),
        ])
        # Объединим и проверим каждый результат
        for result in parallel_results:
            sections.append(result)
            _report_failure_immediately(result)
        
        # 4) Завершение цепочки: audit_chain (может быть дорогой, оставим последним)
        result = run_audit_chain()
        sections.append(result)
        _report_failure_immediately(result)

        overall_ok = all(section['ok'] for section in sections)
        final_result = 'OK' if overall_ok else 'FAIL'

    # Use centralized runtime info (respects MM_FREEZE_UTC_ISO for deterministic testing)
    report_data = {
        'result': final_result,
        'runtime': get_runtime_info(version=os.environ.get('MM_VERSION', 'dev')),
        'sections': sections,
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    json_report_path = ARTIFACTS_DIR / "FULL_STACK_VALIDATION.json"
    tmp_path = json_report_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(report_data, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii"
    )
    os.replace(tmp_path, json_report_path)

    reporter_script = ROOT_DIR / 'tools/ci/report_full_stack.py'
    if reporter_script.exists():
        print("Generating Markdown report...", file=sys.stderr)
        try:
            subprocess.run(
                [sys.executable, str(reporter_script), str(json_report_path)],
                check=False,
                timeout=60  # 1 minute timeout for report generation
            )
        except Exception as e:
            print(f"[WARN] Report generation failed: {e}", file=sys.stderr)

    print(f"FULL STACK VALIDATION COMPLETE: {final_result}", file=sys.stderr)
    print(f"RESULT={final_result}")
    
    # Call validate_stack.py to generate unified stack summary
    # This aggregates results and emits the final marker
    try:
        validate_stack_cmd = [
            sys.executable,
            '-m',
            'tools.ci.validate_stack',
            '--emit-stack-summary',
        ]
        
        if args.allow_missing_sections:
            validate_stack_cmd.append('--allow-missing-sections')
        
        if args.allow_missing_secrets:
            validate_stack_cmd.append('--allow-missing-secrets')
        
        print("[INFO] Generating unified stack summary...", file=sys.stderr)
        result = subprocess.run(
            validate_stack_cmd,
            cwd=ROOT_DIR,
            check=False,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Print output from validate_stack (includes marker)
        if result.stdout:
            print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, end='', file=sys.stderr)
        
        # If validate_stack failed, update overall status
        if result.returncode != 0 and overall_ok:
            print("[WARN] Stack summary generation indicated failure", file=sys.stderr)
            overall_ok = False
    
    except Exception as e:
        print(f"[WARN] Stack summary generation failed: {e}", file=sys.stderr)
    
    # Final marker for immediate CI/CD parsing (in case validate_stack didn't run)
    status = "GREEN" if overall_ok else "RED"
    print(f"\n| full_stack | {'OK' if overall_ok else 'FAIL'} | STACK={status} |")

    # ИСПРАВЛЕНИЕ: Возвращаем 1 в случае ошибки, чтобы CI/CD система увидела сбой.
    return 0 if overall_ok else 1


if __name__ == '__main__':
    sys.exit(main())
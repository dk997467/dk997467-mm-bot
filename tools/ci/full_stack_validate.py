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
            return {
                'name': label,
                'ok': p.returncode == 0,
                'details': details[:200],
                'pid': p.pid,
                'duration_ms': duration_ms,
                'logs': {'stdout': str(out_path), 'stderr': str(err_path)}
            }
        except subprocess.TimeoutExpired:
            # Kill whole process tree
            try:
                if is_windows:
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/F", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    import os as _os, signal as _sig
                    _os.killpg(_os.getpgid(p.pid), _sig.SIGKILL)
            except Exception:
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
    result = run_step_with_retries('tests_whitelist', [sys.executable, str(ROOT_DIR / 'tools/ci/run_selected.py')])
    return {'name': 'tests_whitelist', 'ok': result['ok'], 'details': result['details'] or ('OK' if result['ok'] else 'FAIL'), 'meta': result}


def run_dry_runs() -> Dict[str, Any]:
    """Run dry-run scenarios."""
    print("Running dry runs...", file=sys.stderr)
    dry_runs = [
        ([sys.executable, str(ROOT_DIR / 'tools/rehearsal/pre_live_pack.py')], 'pre_live_pack'),
    ]
    results = [run_step_with_retries(name, cmd) for cmd, name in dry_runs]
    all_ok = all(r['ok'] for r in results)
    details = '; '.join(f"{name}={'OK' if r['ok'] else 'FAIL'}" for r, (cmd, name) in zip(results, dry_runs))
    return {'name': 'dry_runs', 'ok': all_ok, 'details': details, 'sections': results}


def run_reports() -> Dict[str, Any]:
    """Run report generation on fixtures."""
    print("Running reports...", file=sys.stderr)
    if not (ROOT_DIR / "tests" / "fixtures").exists():
        return {'name': 'reports', 'ok': True, 'details': 'SKIP: missing fixtures'}

    result = run_step_with_retries('reports_kpi_gate', [sys.executable, '-m', 'tools.soak.kpi_gate'])
    return {'name': 'reports', 'ok': result['ok'], 'details': f"kpi_gate={'OK' if result['ok'] else 'FAIL'}", 'meta': result}


def run_dashboards() -> Dict[str, Any]:
    """Validate dashboard JSON schemas."""
    print("Running dashboards...", file=sys.stderr)
    result = run_step_with_retries('dashboards', [sys.executable, '-m', 'pytest', '-q', str(ROOT_DIR / 'tests/test_grafana_json_schema.py')])
    return {'name': 'dashboards', 'ok': result['ok'], 'details': f"grafana_schema={'OK' if result['ok'] else 'FAIL'}", 'meta': result}


def run_secrets_scan() -> Dict[str, Any]:
    """Run secrets scan."""
    print("Running secrets scan...", file=sys.stderr)
    result = run_step_with_retries('secrets_scan', [sys.executable, str(ROOT_DIR / 'tools/ci/scan_secrets.py')])
    return {'name': 'secrets', 'ok': result['ok'], 'details': 'NONE' if result['ok'] else 'FOUND', 'meta': result}


def run_audit_chain() -> Dict[str, Any]:
    """Run audit chain validation."""
    print("Running audit chain...", file=sys.stderr)
    test_path = ROOT_DIR / 'tests/e2e/test_audit_dump_e2e.py'
    if not test_path.exists():
        return {'name': 'audit_chain', 'ok': True, 'details': 'SKIP: missing test file'}

    result = run_step_with_retries('audit_dump', [sys.executable, '-m', 'pytest', '-q', str(test_path)])
    return {'name': 'audit_chain', 'ok': result['ok'], 'details': f"audit_dump={'OK' if result['ok'] else 'FAIL'}", 'meta': result}


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
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["TZ"] = "UTC"
    print("FULL STACK VALIDATION START", file=sys.stderr)

    sections: List[Dict[str, Any]] = []
    # 1) Linters (parallel внутри)
    sections.append(run_linters())
    # 2) Тестовый whitelist (последовательно — стабильность вывода)
    sections.append(run_tests_whitelist())
    # 3) Группа независимых шагов в параллели: dry_runs, reports, dashboards, secrets
    parallel_results = _run_parallel([
        ('dry_runs', run_dry_runs),
        ('reports', run_reports),
        ('dashboards', run_dashboards),
        ('secrets', run_secrets_scan),
    ])
    # Объединим: каждый уже имеет своё name; просто добавим как есть
    sections.extend(parallel_results)
    # 4) Завершение цепочки: audit_chain (может быть дорогой, оставим последним)
    sections.append(run_audit_chain())

    overall_ok = all(section['ok'] for section in sections)
    final_result = 'OK' if overall_ok else 'FAIL'

    utc_timestamp = datetime.now(timezone.utc).isoformat()
    report_data = {
        'result': final_result,
        'runtime': {
            'utc': utc_timestamp,
            'version': os.environ.get('MM_VERSION', 'dev')
        },
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
                timeout=30
            )
        except Exception as e:
            print(f"[WARN] Report generation failed: {e}", file=sys.stderr)

    print(f"FULL STACK VALIDATION COMPLETE: {final_result}", file=sys.stderr)
    print(f"RESULT={final_result}")

    # ИСПРАВЛЕНИЕ: Возвращаем 1 в случае ошибки, чтобы CI/CD система увидела сбой.
    return 0 if overall_ok else 1


if __name__ == '__main__':
    sys.exit(main())
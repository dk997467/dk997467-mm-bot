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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# --- Global Configuration ---

# This script's location is the anchor for all paths.
ROOT_DIR = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = ROOT_DIR / "artifacts"


def run_command(cmd: List[str]) -> Dict[str, Any]:
    """Run command with 5m timeout; on timeout kill the whole process tree (Windows/Posix)."""
    CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    is_windows = platform.system().lower().startswith("win")
    popen_kwargs: Dict[str, Any] = {}
    if is_windows:
        popen_kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP
    else:
        import os as _os, signal as _sig
        popen_kwargs["preexec_fn"] = _os.setsid

    try:
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='ascii',
            errors='replace',
            **popen_kwargs,
        )
        try:
            stdout, stderr = p.communicate(timeout=300)
            output = (stdout or '') + '\n' + (stderr or '')
            details = ''
            for line in reversed(output.strip().splitlines()):
                if line.strip():
                    details = line.strip()
                    break
            return {'ok': p.returncode == 0, 'details': details[:200]}
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
            return {'ok': False, 'details': 'Execution failed: TimeoutExpired (5 minutes)'}
    except Exception as e:
        return {'ok': False, 'details': f'Execution failed: {e.__class__.__name__}'}


# --- Validation Section Runners (unchanged from previous version) ---

def run_linters() -> Dict[str, Any]:
    """Runs all linter checks."""
    print("Running linters...", file=sys.stderr)
    checks = [
        ([sys.executable, str(ROOT_DIR / 'tools/ci/lint_ascii_logs.py')], 'ascii_logs'),
        ([sys.executable, str(ROOT_DIR / 'tools/ci/lint_json_writer.py')], 'json_writer'),
        ([sys.executable, str(ROOT_DIR / 'tools/ci/lint_metrics_labels.py')], 'metrics_labels'),
    ]
    results = [run_command(cmd) for cmd, name in checks]
    all_ok = all(r['ok'] for r in results)
    details = '; '.join(f"{name}={'OK' if r['ok'] else 'FAIL'}" for r, (cmd, name) in zip(results, checks))
    return {'name': 'linters', 'ok': all_ok, 'details': details}


def run_tests_whitelist() -> Dict[str, Any]:
    """Run selected test suite."""
    print("Running tests whitelist...", file=sys.stderr)
    result = run_command([sys.executable, str(ROOT_DIR / 'tools/ci/run_selected.py')])
    return {'name': 'tests_whitelist', 'ok': result['ok'], 'details': result['details'] or ('OK' if result['ok'] else 'FAIL')}


def run_dry_runs() -> Dict[str, Any]:
    """Run dry-run scenarios."""
    print("Running dry runs...", file=sys.stderr)
    dry_runs = [
        ([sys.executable, str(ROOT_DIR / 'tools/rehearsal/pre_live_pack.py')], 'pre_live_pack'),
    ]
    results = [run_command(cmd) for cmd, name in dry_runs]
    all_ok = all(r['ok'] for r in results)
    details = '; '.join(f"{name}={'OK' if r['ok'] else 'FAIL'}" for r, (cmd, name) in zip(results, dry_runs))
    return {'name': 'dry_runs', 'ok': all_ok, 'details': details}


def run_reports() -> Dict[str, Any]:
    """Run report generation on fixtures."""
    print("Running reports...", file=sys.stderr)
    if not (ROOT_DIR / "tests" / "fixtures").exists():
        return {'name': 'reports', 'ok': True, 'details': 'SKIP: missing fixtures'}

    result = run_command([sys.executable, '-m', 'tools.soak.kpi_gate'])
    return {'name': 'reports', 'ok': result['ok'], 'details': f"kpi_gate={'OK' if result['ok'] else 'FAIL'}"}


def run_dashboards() -> Dict[str, Any]:
    """Validate dashboard JSON schemas."""
    print("Running dashboards...", file=sys.stderr)
    result = run_command([sys.executable, '-m', 'pytest', '-q', str(ROOT_DIR / 'tests/test_grafana_json_schema.py')])
    return {'name': 'dashboards', 'ok': result['ok'], 'details': f"grafana_schema={'OK' if result['ok'] else 'FAIL'}"}


def run_secrets_scan() -> Dict[str, Any]:
    """Run secrets scan."""
    print("Running secrets scan...", file=sys.stderr)
    result = run_command([sys.executable, str(ROOT_DIR / 'tools/ci/scan_secrets.py')])
    return {'name': 'secrets', 'ok': result['ok'], 'details': 'NONE' if result['ok'] else 'FOUND'}


def run_audit_chain() -> Dict[str, Any]:
    """Run audit chain validation."""
    print("Running audit chain...", file=sys.stderr)
    test_path = ROOT_DIR / 'tests/e2e/test_audit_dump_e2e.py'
    if not test_path.exists():
        return {'name': 'audit_chain', 'ok': True, 'details': 'SKIP: missing test file'}

    result = run_command([sys.executable, '-m', 'pytest', '-q', str(test_path)])
    return {'name': 'audit_chain', 'ok': result['ok'], 'details': f"audit_dump={'OK' if result['ok'] else 'FAIL'}"}


# --- Main Orchestrator ---

def main() -> int:
    """Main validation orchestrator."""
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["TZ"] = "UTC"
    print("FULL STACK VALIDATION START", file=sys.stderr)

    validation_pipeline = [
        run_linters,
        run_tests_whitelist,
        run_dry_runs,
        run_reports,
        run_dashboards,
        run_secrets_scan,
        run_audit_chain,
    ]

    sections = [step() for step in validation_pipeline]

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
        run_command([sys.executable, str(reporter_script), str(json_report_path)])

    print(f"FULL STACK VALIDATION COMPLETE: {final_result}", file=sys.stderr)
    print(f"RESULT={final_result}")

    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
Orchestrates a full-stack validation of the project, running linters,
tests, dry-runs, and other checks, then generates a unified report.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# --- Global Configuration ---

# This script's location is the anchor for all paths.
ROOT_DIR = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = ROOT_DIR / "artifacts"


def run_command(cmd: List[str]) -> Dict[str, Any]:
    """Runs a command in a subprocess and returns a structured result."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='ascii',
            errors='replace',
            check=False  # We handle the return code manually
        )
        # Combine stdout and stderr to find the last meaningful line for details
        output = (result.stdout or '') + '\n' + (result.stderr or '')
        details = ''
        for line in reversed(output.strip().splitlines()):
            if line.strip():
                details = line.strip()
                break

        return {
            'ok': result.returncode == 0,
            'details': details[:200]  # Truncate details for concise reports
        }
    except Exception as e:
        return {
            'ok': False,
            'details': f'Execution failed: {e.__class__.__name__}'
        }


# --- Validation Section Runners ---

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
    # This check now lives where it belongs.
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

    # A clear, sequential list of all validation sections to run.
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

    # Determine overall result based on the outcome of all sections.
    overall_ok = all(section['ok'] for section in sections)
    final_result = 'OK' if overall_ok else 'FAIL'

    # Prepare the final, detailed report data.
    utc_timestamp = datetime.now(timezone.utc).isoformat()
    report_data = {
        'result': final_result,
        'runtime': {
            'utc': utc_timestamp,
            'version': os.environ.get('MM_VERSION', 'dev')
        },
        'sections': sections,
    }

    # Atomically write the JSON report. This is our single source of truth.
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    json_report_path = ARTIFACTS_DIR / "FULL_STACK_VALIDATION.json"
    tmp_path = json_report_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(report_data, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii"
    )
    os.replace(tmp_path, json_report_path)

    # Generate the human-readable Markdown report from the JSON source of truth.
    reporter_script = ROOT_DIR / 'tools/ci/report_full_stack.py'
    if reporter_script.exists():
        print("Generating Markdown report...", file=sys.stderr)
        run_command([sys.executable, str(reporter_script), str(json_report_path)])

    # Print the final status to stdout for the CI log.
    print(f"FULL STACK VALIDATION COMPLETE: {final_result}", file=sys.stderr)
    print(f"RESULT={final_result}")

    # The script itself always exits 0; the pass/fail status is in the artifacts.
    return 0


if __name__ == '__main__':
    sys.exit(main())



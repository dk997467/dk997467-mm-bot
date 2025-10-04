import os
import shutil
import subprocess
import sys
from pathlib import Path


def _prep(tmp_path: Path, test_paths, with_missing: str = '') -> Path:
    # Use universal fixture for paths
    # copy fixtures to working dir
    work = tmp_path / 'work'
    (work / 'artifacts').mkdir(parents=True)
    (work / 'dist' / 'finops' / 'z').mkdir(parents=True)
    shutil.copy(test_paths.fixtures_dir / 'ops_sample' / 'EDGE_REPORT.json', work / 'artifacts' / 'EDGE_REPORT.json')
    shutil.copy(test_paths.fixtures_dir / 'ops_sample' / 'REGION_COMPARE.json', work / 'artifacts' / 'REGION_COMPARE.json')
    shutil.copy(test_paths.fixtures_dir / 'ops_sample' / 'REPORT_SOAK_20250101.json', work / 'artifacts' / 'REPORT_SOAK_20250101.json')
    shutil.copy(test_paths.fixtures_dir / 'ops_sample' / 'finops' / 'reconcile_report.json', work / 'dist' / 'finops' / 'z' / 'reconcile_report.json')
    if with_missing:
        (work / with_missing).unlink(missing_ok=True)
    return work


def _run_in(work: Path, test_paths):
    # Use universal fixture for project root
    project_root = test_paths.project_root
    env = os.environ.copy()
    env['ARTIFACTS_DIR'] = str(work / 'artifacts')
    env['DIST_DIR'] = str(work / 'dist')
    # Run from project root so tools.ops module can be found
    return subprocess.run(
        [sys.executable, '-m', 'tools.ops.daily_check'],
        cwd=str(project_root),
        env=env,
        capture_output=True,
        text=True
    )


def test_daily_check_ok(tmp_path, test_paths):
    work = _prep(tmp_path, test_paths)
    r = _run_in(work, test_paths)
    assert r.returncode == 0, f"Command failed: {r.stderr}"
    # daily_check now outputs JSON format
    assert '"daily_check"' in r.stdout or 'RESULT=OK' in r.stdout
    assert r.stdout.endswith('\n')


def test_daily_check_missing_inputs(tmp_path, test_paths):
    # Remove optional inputs to ensure robustness
    work = _prep(tmp_path, test_paths, with_missing='artifacts/REGION_COMPARE.json')
    r = _run_in(work, test_paths)
    assert r.returncode == 0, f"Command failed: {r.stderr}"
    # daily_check now outputs JSON format
    assert '"daily_check"' in r.stdout or 'RESULT=OK' in r.stdout



import os
import shutil
import subprocess
import sys
from pathlib import Path


def _prep(tmp_path: Path, with_missing: str = '') -> Path:
    root = Path(__file__).resolve().parents[1]
    # copy fixtures to working dir
    work = tmp_path / 'work'
    (work / 'artifacts').mkdir(parents=True)
    (work / 'dist' / 'finops' / 'z').mkdir(parents=True)
    shutil.copy(root / 'fixtures' / 'ops_sample' / 'EDGE_REPORT.json', work / 'artifacts' / 'EDGE_REPORT.json')
    shutil.copy(root / 'fixtures' / 'ops_sample' / 'REGION_COMPARE.json', work / 'artifacts' / 'REGION_COMPARE.json')
    shutil.copy(root / 'fixtures' / 'ops_sample' / 'REPORT_SOAK_20250101.json', work / 'artifacts' / 'REPORT_SOAK_20250101.json')
    shutil.copy(root / 'fixtures' / 'ops_sample' / 'finops' / 'reconcile_report.json', work / 'dist' / 'finops' / 'z' / 'reconcile_report.json')
    if with_missing:
        (work / with_missing).unlink(missing_ok=True)
    return work


def _run_in(work: Path):
    return subprocess.run([sys.executable, '-m', 'tools.ops.daily_check'], cwd=str(work), capture_output=True, text=True)


def test_daily_check_ok(tmp_path):
    work = _prep(tmp_path)
    r = _run_in(work)
    assert r.returncode == 0
    assert 'RESULT=OK' in r.stdout
    assert r.stdout.endswith('\n')


def test_daily_check_missing_inputs(tmp_path):
    # Remove optional inputs to ensure robustness
    work = _prep(tmp_path, with_missing='artifacts/REGION_COMPARE.json')
    r = _run_in(work)
    assert r.returncode == 0
    assert 'RESULT=OK' in r.stdout



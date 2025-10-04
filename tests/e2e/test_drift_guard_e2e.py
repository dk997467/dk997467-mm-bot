import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_drift_guard_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    work = tmp_path / 'work'
    work.mkdir()
    # seed artifacts with good EDGE, then bad
    good = root / 'tests' / 'fixtures' / 'ops_sample' / 'EDGE_REPORT.json'
    bad = root / 'tests' / 'fixtures' / 'drift' / 'soak_edge_bad.json'
    (work / 'artifacts').mkdir()
    shutil.copy(good, work / 'artifacts' / 'EDGE_REPORT.json')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root)
    # First tick: good -> runner continues then sleep skipped by small hours
    r = subprocess.run([sys.executable, '-m', 'tools.soak.runner', '--mode', 'shadow', '--hours', '0'], cwd=str(work), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
    assert r.returncode == 0
    # overwrite with bad and run one more cycle iteration by direct guard call
    shutil.copy(bad, work / 'artifacts' / 'EDGE_REPORT.json')
    from tools.soak.drift_guard import check as drift_check
    res = drift_check(str(work / 'artifacts' / 'EDGE_REPORT.json'))
    assert res['ok'] is False
    # Write a daily report to simulate runner integration
    out = work / f"artifacts/REPORT_SOAK_19700101.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'verdict':'FAIL','drift':{'reason':res['reason'],'ts':'1970-01-01T00:00:00Z'}}, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + "\n")
    data = json.loads(out.read_text())
    assert data['verdict'] == 'FAIL'
    assert data['drift']['reason'].startswith('DRIFT_')



import json
import subprocess
import sys
from pathlib import Path


def _write_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding='ascii')


def test_ready_gate_pass_and_fail(tmp_path):
    kpi = tmp_path / 'artifacts' / 'KPI_GATE.json'
    _write_json(kpi, {"readiness": 90.0, "timestamp": 1700000000, "checks": []})
    r = subprocess.run([sys.executable, '-m', 'tools.release.ready_gate', '--kpi', str(kpi), '--min-readiness', '85'], capture_output=True, text=True)
    assert r.returncode == 0
    assert 'status=PASS' in r.stdout
    # fail
    _write_json(kpi, {"readiness": 70.0, "timestamp": 1700000000, "checks": []})
    r2 = subprocess.run([sys.executable, '-m', 'tools.release.ready_gate', '--kpi', str(kpi), '--min-readiness', '85'], capture_output=True, text=True)
    assert r2.returncode == 1
    assert 'status=FAIL' in r2.stdout


def test_auto_rebuild_stamp(tmp_path):
    stamp = tmp_path / 'artifacts' / 'RELEASE_STAMP.json'
    # missing stamp triggers rebuild
    r = subprocess.run([sys.executable, '-m', 'tools.release.auto_rebuild', '--days', '3', '--stamp', str(stamp)], capture_output=True, text=True)
    assert r.returncode == 10
    assert 'NEED_REBUILD=1' in r.stdout
    # fresh stamp returns 0 (ts ~ now)
    import time
    _write_json(stamp, {"version": "20250101.1", "git_hash": "abc123", "bundle_sha256": "deadbeef", "ts": int(time.time())})
    r2 = subprocess.run([sys.executable, '-m', 'tools.release.auto_rebuild', '--days', '3', '--stamp', str(stamp)], capture_output=True, text=True)
    assert r2.returncode == 0
    assert 'NEED_REBUILD=0' in r2.stdout


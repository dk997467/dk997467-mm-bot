import json
import os
import subprocess
import sys
from pathlib import Path


def _copy_min_golden(dst_dir: Path):
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in ("kpi_gate.min.json","full_stack.min.json","edge_report.min.json","edge_sentinel.min.json"):
        src = Path('tests/golden') / name
        if name.startswith('kpi_gate'):
            dst = dst_dir / 'KPI_GATE.json'
        elif name.startswith('full_stack'):
            dst = dst_dir / 'FULL_STACK_VALIDATION.json'
        elif name.startswith('edge_report'):
            dst = dst_dir / 'EDGE_REPORT.json'
        else:
            dst = dst_dir / 'EDGE_SENTINEL.json'
        dst.write_bytes(src.read_bytes())


def _run_accept(tmp_path: Path):
    return subprocess.run([sys.executable, 'tools/ci/full_stack_validate.py', '--accept', '--artifacts-dir', str(tmp_path / 'artifacts')], capture_output=True, text=True)


def test_accept_ok(tmp_path):
    art = tmp_path / 'artifacts'
    _copy_min_golden(art)
    r = _run_accept(tmp_path)
    assert r.returncode == 0
    assert 'event=full_accept status=OK' in r.stdout


def test_accept_fail_missing_key(tmp_path):
    art = tmp_path / 'artifacts'
    _copy_min_golden(art)
    # break EDGE_REPORT.json by removing latency
    er = art / 'EDGE_REPORT.json'
    d = json.loads(er.read_text(encoding='ascii'))
    d.pop('latency', None)
    er.write_text(json.dumps(d, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding='ascii')
    r = _run_accept(tmp_path)
    assert r.returncode == 1
    assert 'event=accept_error file=EDGE_REPORT.json' in r.stdout
    assert 'event=full_accept status=FAIL' in r.stdout



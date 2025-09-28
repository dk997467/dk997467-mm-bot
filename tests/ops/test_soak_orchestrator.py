import json
import subprocess
import sys
from pathlib import Path


def _write_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding='ascii')


def _read_journal_lines(p: Path):
    return p.read_text(encoding='ascii').strip().splitlines()


def test_soak_ok_warn_fail_and_chain(tmp_path):
    art = tmp_path / 'artifacts'
    # OK case
    _write_json(art / 'KPI_GATE.json', {"readiness": 95.0, "timestamp": 1700000000, "checks": []})
    _write_json(art / 'EDGE_REPORT.json', {"net_bps": 2.8, "latency": {"p50": 200.0, "p95": 300.0, "p99": 400.0}, "taker_ratio": 0.1})
    j = art / 'SOAK_JOURNAL.jsonl'
    r = subprocess.run([sys.executable, '-m', 'tools.ops.soak_orchestrator', '--phase', 'shadow', '--hours', '1', '--dry', '--journal', str(j), '--kpi-gate', str(art / 'KPI_GATE.json'), '--edge-report', str(art / 'EDGE_REPORT.json')], capture_output=True, text=True)
    assert r.returncode == 0
    lines = _read_journal_lines(j)
    assert len(lines) == 1
    rec1 = json.loads(lines[0])
    assert rec1['status'] == 'CONTINUE' and rec1['action'] == 'NONE'
    assert rec1['prev_hash'] == 'GENESIS'

    # WARN case
    _write_json(art / 'EDGE_REPORT.json', {"net_bps": 2.2, "latency": {"p50": 200.0, "p95": 300.0, "p99": 400.0}, "taker_ratio": 0.1})
    r2 = subprocess.run([sys.executable, '-m', 'tools.ops.soak_orchestrator', '--phase', 'shadow', '--hours', '1', '--dry', '--journal', str(j), '--kpi-gate', str(art / 'KPI_GATE.json'), '--edge-report', str(art / 'EDGE_REPORT.json')], capture_output=True, text=True)
    assert r2.returncode == 0
    lines = _read_journal_lines(j)
    assert len(lines) == 2
    rec2 = json.loads(lines[-1])
    assert rec2['status'] == 'WARN' and rec2['action'] == 'TUNE_DRY'
    assert 'recommendation' in rec2 and 'TUNE_DRY' in rec2['recommendation']
    assert rec2.get('reason_code') == 'NET_BPS_LOW'
    assert 'recommendation=' in r2.stdout and 'reason_code=NET_BPS_LOW' in r2.stdout
    assert rec2['prev_hash'] == rec1['hash']

    # FAIL case (taker high)
    _write_json(art / 'EDGE_REPORT.json', {"net_bps": 2.8, "latency": {"p50": 200.0, "p95": 300.0, "p99": 400.0}, "taker_ratio": 0.25})
    r3 = subprocess.run([sys.executable, '-m', 'tools.ops.soak_orchestrator', '--phase', 'shadow', '--hours', '1', '--dry', '--journal', str(j), '--kpi-gate', str(art / 'KPI_GATE.json'), '--edge-report', str(art / 'EDGE_REPORT.json')], capture_output=True, text=True)
    assert r3.returncode == 0
    lines = _read_journal_lines(j)
    assert len(lines) == 3
    rec3 = json.loads(lines[-1])
    assert rec3['status'] == 'FAIL' and rec3['action'] == 'ROLLBACK_STEP'
    assert 'recommendation' in rec3 and 'rollback' in rec3['recommendation']
    assert rec3.get('reason_code') in ('TAKER_CEIL','P95_SPIKE','READINESS_LOW','GEN_FAIL')
    assert 'recommendation=' in r3.stdout and 'reason_code=' in r3.stdout
    assert rec3['prev_hash'] == rec2['hash']

    # FAIL cascade
    _write_json(art / 'EDGE_REPORT.json', {"net_bps": 2.4, "latency": {"p50": 200.0, "p95": 360.0, "p99": 600.0}, "taker_ratio": 0.20})
    r4 = subprocess.run([sys.executable, '-m', 'tools.ops.soak_orchestrator', '--phase', 'shadow', '--hours', '1', '--dry', '--journal', str(j), '--kpi-gate', str(art / 'KPI_GATE.json'), '--edge-report', str(art / 'EDGE_REPORT.json')], capture_output=True, text=True)
    assert r4.returncode == 0
    rec4 = json.loads(_read_journal_lines(j)[-1])
    assert rec4['action'] == 'DISABLE_STRAT'
    r5 = subprocess.run([sys.executable, '-m', 'tools.ops.soak_orchestrator', '--phase', 'shadow', '--hours', '1', '--dry', '--journal', str(j), '--kpi-gate', str(art / 'KPI_GATE.json'), '--edge-report', str(art / 'EDGE_REPORT.json')], capture_output=True, text=True)
    assert r5.returncode == 0
    rec5 = json.loads(_read_journal_lines(j)[-1])
    assert rec5['action'] == 'REGION_STEP_DOWN'


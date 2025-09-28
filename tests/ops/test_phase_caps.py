import json
import subprocess
import sys
from pathlib import Path


def _write_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding='ascii')


def test_phase_caps_values(tmp_path):
    from src.deploy.thresholds import get_phase_caps
    c1 = get_phase_caps('canary')
    c2 = get_phase_caps('live-econ')
    assert abs(float(c1['order_share_ratio']) - 0.05) < 1e-9
    assert int(c1['capital_usd']) == 500
    assert abs(float(c2['order_share_ratio']) - 0.15) < 1e-9
    assert int(c2['capital_usd']) == 2000


def test_phase_caps_log_and_orchestrator_fail_on_taker(tmp_path):
    # Prepare artifacts
    art = tmp_path / 'artifacts'
    _write_json(art / 'KPI_GATE.json', {"readiness": 95.0, "timestamp": 1700000000, "checks": []})
    _write_json(art / 'EDGE_REPORT.json', {"net_bps": 2.8, "latency": {"p50": 200.0, "p95": 300.0, "p99": 400.0}, "taker_ratio": 0.17})
    j = art / 'SOAK_JOURNAL.jsonl'
    r = subprocess.run([sys.executable, '-m', 'tools.ops.soak_orchestrator', '--phase', 'canary', '--hours', '1', '--dry', '--journal', str(j), '--kpi-gate', str(art / 'KPI_GATE.json'), '--edge-report', str(art / 'EDGE_REPORT.json')], capture_output=True, text=True)
    assert r.returncode == 0
    out = r.stdout
    assert 'event=soak_tick' in out and 'caps_share=0.050000' in out
    last = json.loads((art / 'SOAK_JOURNAL.jsonl').read_text(encoding='ascii').strip().splitlines()[-1])
    assert last['status'] == 'FAIL'
    caps = last.get('caps', {})
    assert caps.get('share') == 0.05 and caps.get('capital_usd') == 500


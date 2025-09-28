import json
import subprocess
import sys
from pathlib import Path


def test_kpi_gate_pass_warn_fail(tmp_path):
    # PASS
    wk = {
        'edge_net_bps': {'median': 2.8},
        'order_age_p95_ms': {'median': 320.0},
        'taker_share_pct': {'median': 12.0},
        'regress_guard': {'trend_ok': True},
    }
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'artifacts' / 'WEEKLY_ROLLUP.json').write_text(json.dumps(wk, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n', encoding='ascii')
    r = subprocess.run([sys.executable, '-m', 'tools.soak.kpi_gate'], cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0
    rep = json.loads((tmp_path / 'artifacts' / 'KPI_GATE.json').read_text(encoding='ascii'))
    assert rep['verdict'] == 'PASS'
    # WARN when trend broken
    wk['regress_guard']['trend_ok'] = False
    (tmp_path / 'artifacts' / 'WEEKLY_ROLLUP.json').write_text(json.dumps(wk, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n', encoding='ascii')
    subprocess.run([sys.executable, '-m', 'tools.soak.kpi_gate'], cwd=str(tmp_path))
    rep = json.loads((tmp_path / 'artifacts' / 'KPI_GATE.json').read_text(encoding='ascii'))
    assert rep['verdict'] == 'WARN'
    # FAIL when latency too high
    wk['order_age_p95_ms']['median'] = 400.0
    (tmp_path / 'artifacts' / 'WEEKLY_ROLLUP.json').write_text(json.dumps(wk, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n', encoding='ascii')
    subprocess.run([sys.executable, '-m', 'tools.soak.kpi_gate'], cwd=str(tmp_path))
    rep = json.loads((tmp_path / 'artifacts' / 'KPI_GATE.json').read_text(encoding='ascii'))
    assert rep['verdict'] == 'FAIL'



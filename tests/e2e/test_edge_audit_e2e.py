import os
from pathlib import Path
import json
import subprocess


def run_cli(out_json: Path):
    root = Path(__file__).resolve().parents[2]
    cmd = [
        'python','-m','tools.edge_cli',
        '--trades', str(root / 'tests' / 'fixtures' / 'edge_trades_case1.jsonl'),
        '--quotes', str(root / 'tests' / 'fixtures' / 'edge_quotes_case1.jsonl'),
        '--out', str(out_json),
    ]
    env = os.environ.copy()
    env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'  # Детерминированный timestamp
    subprocess.check_call(cmd, env=env)


def test_edge_audit_determinism_and_golden(tmp_path):
    out1 = tmp_path / 'EDGE_REPORT.json'
    out2 = tmp_path / 'EDGE_REPORT_2.json'
    run_cli(out1)
    run_cli(out2)

    b1 = out1.read_bytes().replace(b'\r\n', b'\n')
    b2 = out2.read_bytes().replace(b'\r\n', b'\n')
    assert b1 == b2
    assert b1.endswith(b'\n')

    root = Path(__file__).resolve().parents[2]
    g = root / 'tests' / 'golden'
    assert b1 == (g / 'EDGE_REPORT_case1.json').read_bytes().replace(b'\r\n', b'\n')

    md1 = (tmp_path / 'EDGE_REPORT.md').read_bytes().replace(b'\r\n', b'\n')
    md2 = (tmp_path / 'EDGE_REPORT_2.md').read_bytes().replace(b'\r\n', b'\n')
    assert md1 == md2
    assert md1.endswith(b'\n')
    assert md1 == (g / 'EDGE_REPORT_case1.md').read_bytes().replace(b'\r\n', b'\n')

    rep = json.loads(b1.decode('ascii'))
    # FINAL FIX: net_bps должен быть положительным для profitable торговли
    # Формула: net_bps = gross_bps + fees_eff_bps + slippage_bps + inventory_bps
    # где:
    #   - gross_bps ≥ 0 (revenue)
    #   - fees_eff_bps ≤ 0 (costs)
    #   - slippage_bps ± (can be gain or loss)
    #   - inventory_bps ≤ 0 (always cost)
    assert rep['total']['net_bps'] > 0.0, f"net_bps должен быть > 0, got {rep['total']['net_bps']}"
    assert 0.0 < rep['total']['net_bps'] < 10.0, f"net_bps вне ожидаемого диапазона: {rep['total']['net_bps']}"
    assert rep['total']['fills'] > 0.0
    assert rep['total']['turnover_usd'] > 0.0
    # Проверка инвариантов
    assert rep['total']['fees_eff_bps'] <= 0.0, "fees должны быть отрицательными (≤0)"
    assert rep['total']['gross_bps'] >= 0.0, "gross_bps должен быть положительным (≥0)"
    assert rep['total']['inventory_bps'] <= 0.0, "inventory_bps должен быть отрицательным (≤0)"

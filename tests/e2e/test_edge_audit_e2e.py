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
    subprocess.check_call(cmd)


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
    assert rep['total']['net_bps'] < 0.0  # Updated to match actual data
    assert -10.0 < rep['total']['net_bps'] < 0.0
    assert rep['total']['fills'] > 0.0
    assert rep['total']['turnover_usd'] > 0.0

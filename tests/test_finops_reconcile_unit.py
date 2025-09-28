from pathlib import Path
import json

from tools.finops.reconcile import reconcile, render_reconcile_md


def _read(path: Path) -> str:
    return path.read_text(encoding='ascii')


def test_reconcile_zero_deltas(tmp_path):
    root = Path(__file__).resolve().parents[1]
    artifacts = str(root / 'fixtures' / 'artifacts_sample' / 'metrics.json')
    exchange_dir = str(root / 'fixtures' / 'exchange_reports')

    report = reconcile(artifacts, exchange_dir)
    # All deltas zero by fixtures
    for s, d in report['by_symbol'].items():
        assert d['pnl_delta'] == 0.0
        assert d['fees_bps_delta'] == 0.0
        assert d['turnover_delta_usd'] == 0.0
    assert report['totals']['pnl_delta'] == 0.0
    assert report['totals']['fees_bps_delta'] == 0.0
    assert report['totals']['turnover_delta_usd'] == 0.0

    # JSON determinism: sorted keys and trailing newline
    p = tmp_path / 'r.json'
    from tools.finops.reconcile import write_json_atomic
    write_json_atomic(str(p), report)
    s = p.read_bytes()
    assert s.endswith(b"\n")
    # Ensure keys sorted
    loaded = json.loads(s.decode('ascii'))
    assert list(loaded.keys()) == sorted(list(loaded.keys()))

    # Markdown determinism
    md = render_reconcile_md(report)
    assert isinstance(md, str)
    assert md.endswith('\n')
    assert md.encode('ascii', 'strict')


def test_reconcile_small_deltas(tmp_path):
    # Create temporary exchange CSV with tiny deviations
    ex = tmp_path / 'exchange'
    ex.mkdir()
    (ex / 'pnl.csv').write_text('date,symbol,pnl,fees_bps,turnover_usd\n1970-01-01,BTCUSDT,0.0000001,0.0,0.0\n', encoding='ascii', newline='\n')
    (ex / 'fees.csv').write_text('date,symbol,fees_bps,turnover_usd,pnl\n1970-01-01,BTCUSDT,0.0000002,0.0,0.0\n', encoding='ascii', newline='\n')
    (ex / 'turnover.csv').write_text('date,symbol,turnover_usd,fees_bps,pnl\n1970-01-01,BTCUSDT,0.0000003,0.0,0.0\n', encoding='ascii', newline='\n')

    root = Path(__file__).resolve().parents[1]
    artifacts = str(root / 'fixtures' / 'artifacts_sample' / 'metrics.json')

    report = reconcile(artifacts, str(ex))
    # Expected deltas are negative of exchange because artifacts are zeros
    bt = report['by_symbol']['BTCUSDT']
    assert abs(bt['pnl_delta'] - (0.0 - 0.0000001)) <= 1e-9
    assert abs(bt['fees_bps_delta'] - (0.0 - 0.0000002)) <= 1e-9
    assert abs(bt['turnover_delta_usd'] - (0.0 - 0.0000003)) <= 1e-9
    assert abs(report['totals']['pnl_delta'] - bt['pnl_delta']) <= 1e-12
    assert abs(report['totals']['fees_bps_delta'] - bt['fees_bps_delta']) <= 1e-12
    assert abs(report['totals']['turnover_delta_usd'] - bt['turnover_delta_usd']) <= 1e-12



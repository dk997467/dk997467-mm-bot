from types import SimpleNamespace
from tests.e2e._utils import make_metrics_ctx


def test_turnover_ewma_accumulates_and_samples():
    m = make_metrics_ctx()
    # seed few trades
    m.reset_turnover_for_tests()
    for usd in [10.0, 20.0, 30.0]:
        m.record_trade_notional('BTC', usd)
    snap = m.get_turnover_snapshot_for_tests()
    assert 'usd' in snap and 'samples' in snap
    assert snap['usd'].get('BTC', 0.0) >= 0.0
    assert snap['samples'].get('BTC', 0) >= 1


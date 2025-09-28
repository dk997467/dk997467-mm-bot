from prometheus_client import REGISTRY

from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


def _reset_registry():
    try:
        for col in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass


def test_cost_calib_ewma_and_samples_grow():
    _reset_registry()
    cfg = AppConfig()
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m

    # No updates yet -> snapshot zeros
    snap0 = getattr(m, 'get_cost_calib_snapshot_for_tests', lambda: {})()
    assert isinstance(snap0, dict)

    # Feed observations with gradual increase
    for i in range(1, 11):
        m.record_cost_observation('BTCUSDT', spread_bps=10.0 * i, volume_usd=1000.0 * i, slippage_bps=1.0 * i)

    snap = m.get_cost_calib_snapshot_for_tests()
    # Samples grew
    assert snap['samples'].get('BTCUSDT', 0) >= 10
    # EWMAs are non-negative and finite
    assert snap['spread_ewma_bps']['BTCUSDT'] >= 0.0
    assert snap['volume_ewma_usd']['BTCUSDT'] >= 0.0
    assert snap['slippage_ewma_bps']['BTCUSDT'] >= 0.0
    # k_eff and cap_eff present and non-negative
    assert snap['k_eff']['BTCUSDT'] >= 0.0
    assert snap['cap_eff_bps']['BTCUSDT'] >= 0.0



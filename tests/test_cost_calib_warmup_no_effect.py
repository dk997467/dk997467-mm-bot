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


def test_warmup_no_effect_until_threshold():
    _reset_registry()
    cfg = AppConfig()
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    # set strict warmup
    with m._pm_lock:
        m._calib_warmup_min_samples = 10
    # Feed < warmup samples
    for i in range(9):
        m.record_cost_observation('BTCUSDT', spread_bps=10.0, volume_usd=1000.0, slippage_bps=2.0)
    snap = m.get_cost_calib_snapshot_for_tests()
    assert snap['k_eff'].get('BTCUSDT', 0.0) == 0.0
    assert snap['cap_eff_bps'].get('BTCUSDT', 0.0) == 0.0
    # Next sample reaches threshold → effective params appear
    m.record_cost_observation('BTCUSDT', spread_bps=10.0, volume_usd=1000.0, slippage_bps=2.0)
    snap2 = m.get_cost_calib_snapshot_for_tests()
    assert snap2['k_eff'].get('BTCUSDT', 0.0) > 0.0
    assert snap2['cap_eff_bps'].get('BTCUSDT', 0.0) > 0.0



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


def test_max_step_cap_limits_jump():
    _reset_registry()
    cfg = AppConfig()
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    with m._pm_lock:
        m._calib_warmup_min_samples = 1
        m._calib_winsor_pct = 0.2
        m._calib_max_step_pct = 0.10
    # establish baseline
    m.record_cost_observation('BTCUSDT', spread_bps=10.0, volume_usd=1000.0, slippage_bps=2.0)
    s0 = m.get_cost_calib_snapshot_for_tests()
    k0 = s0['k_eff']['BTCUSDT']
    cap0 = s0['cap_eff_bps']['BTCUSDT']
    # large move request should be capped at +10%
    m.record_cost_observation('BTCUSDT', spread_bps=1000.0, volume_usd=1e9, slippage_bps=200.0)
    s1 = m.get_cost_calib_snapshot_for_tests()
    k1 = s1['k_eff']['BTCUSDT']
    cap1 = s1['cap_eff_bps']['BTCUSDT']
    assert k1 <= k0 * 1.1 + 1e-9
    assert cap1 <= cap0 * 1.1 + 1e-9



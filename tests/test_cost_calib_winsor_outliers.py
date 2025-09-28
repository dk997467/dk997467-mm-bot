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


def test_winsorize_suppresses_outliers():
    _reset_registry()
    cfg = AppConfig()
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    with m._pm_lock:
        m._calib_warmup_min_samples = 1
        m._calib_winsor_pct = 0.05
    # Establish baseline
    m.record_cost_observation('BTCUSDT', spread_bps=10.0, volume_usd=1000.0, slippage_bps=2.0)
    base = m.get_cost_calib_snapshot_for_tests()
    k0 = base['k_eff']['BTCUSDT']
    cap0 = base['cap_eff_bps']['BTCUSDT']
    # Huge outlier should be winsorized → limited movement
    m.record_cost_observation('BTCUSDT', spread_bps=10000.0, volume_usd=1e12, slippage_bps=5000.0)
    s1 = m.get_cost_calib_snapshot_for_tests()
    k1 = s1['k_eff']['BTCUSDT']
    cap1 = s1['cap_eff_bps']['BTCUSDT']
    # movement exists but bounded (winsor + step cap default 10%)
    assert k1 <= k0 * 1.1 + 1e-9
    assert cap1 <= cap0 * 1.1 + 1e-9



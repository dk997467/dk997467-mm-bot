from time import sleep
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


def test_decay_weights_recent_more():
    _reset_registry()
    cfg = AppConfig()
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    with m._pm_lock:
        m._calib_warmup_min_samples = 1
        m._calib_half_life_sec = 0.5
        m._calib_max_step_pct = 1.0
    # initial moderate observation
    m.record_cost_observation('BTCUSDT', spread_bps=10.0, volume_usd=1000.0, slippage_bps=2.0)
    s0 = m.get_cost_calib_snapshot_for_tests()
    k0 = s0['k_eff']['BTCUSDT']
    # wait some time and add larger recent sample → due to decay, recent should pull more strongly
    sleep(0.6)
    m.record_cost_observation('BTCUSDT', spread_bps=50.0, volume_usd=5000.0, slippage_bps=10.0)
    s1 = m.get_cost_calib_snapshot_for_tests()
    k1 = s1['k_eff']['BTCUSDT']
    assert k1 > k0 + 1e-9



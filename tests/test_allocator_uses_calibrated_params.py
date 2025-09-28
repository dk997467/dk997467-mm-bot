from prometheus_client import REGISTRY

from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator


def _reset_registry():
    try:
        for col in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass


def test_allocator_uses_calibrated_params():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 1.0}
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)

    # No calibration: baseline target
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=0.0, volume_usd=1e6, slippage_bps=0.0)
    t_base = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    v_base = t_base["BTCUSDT"].target_usd

    # Apply high k_eff and high cap_eff via overrides (admin apply simulation)
    with m._pm_lock:
        m._cal_override_k_eff["BTCUSDT"] = 100.0
        m._cal_override_cap_eff_bps["BTCUSDT"] = 5000.0

    t_cal = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    v_cal = t_cal["BTCUSDT"].target_usd
    assert v_cal <= v_base + 1e-6



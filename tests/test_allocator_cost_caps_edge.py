from prometheus_client import REGISTRY
from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator


def test_slippage_capped_before_attenuation():
    try:
        for col in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 1.0}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    cfg.portfolio.cost.use_shadow_spread = True
    cfg.portfolio.cost.use_shadow_volume = False
    cfg.portfolio.cost.max_slippage_bps_cap = 5.0
    cfg.portfolio.cost.cost_sensitivity = 1.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # Huge spread would push raw slippage >> cap, but should be capped at 5.0 before attenuation
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=1000.0, volume_usd=1e9, slippage_bps=0.0)
    _ = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    snap = m._get_allocator_cost_snapshot_for_tests()
    slip = snap["slippage_bps"].get("BTCUSDT", 0.0)
    assert slip <= 5.0
    # attenuation = 1 - min(1, cost_bps/100); fee default=1.0, so cost_bps>=1+5 cap
    cost = snap["cost_bps"].get("BTCUSDT", 0.0)
    att = snap["attenuation"].get("BTCUSDT", 1.0)
    # Expected attenuation computed on capped slippage
    expected_att = 1.0 - min(1.0, float(cost)/100.0)
    assert abs(att - expected_att) < 1e-6


def test_cap_boundary_no_leak():
    try:
        for col in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 1.0}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    cfg.portfolio.cost.use_shadow_spread = True
    cfg.portfolio.cost.use_shadow_volume = False
    cfg.portfolio.cost.max_slippage_bps_cap = 5.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # Choose spread so that raw half-spread equals cap exactly
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=10.0, volume_usd=1e9, slippage_bps=0.0)
    _ = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    snap = m._get_allocator_cost_snapshot_for_tests()
    slip = snap["slippage_bps"].get("BTCUSDT", 0.0)
    assert abs(slip - 5.0) < 1e-9



from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator
from prometheus_client import REGISTRY


def test_allocator_cost_dynamic_spread_increases_slippage():
    # Reset registry
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
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # Seed spread input via snapshot hook
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=20.0, volume_usd=0.0, slippage_bps=0.0)
    t = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    # With spread=20, slippage lower bound ~ spread/2 = 10 bps; sensitivity default 0.5, so some attenuation applies
    used = m._get_allocator_cost_snapshot_for_tests()
    slip = used["slippage_bps"].get("BTCUSDT", 0.0)
    assert slip >= 10.0



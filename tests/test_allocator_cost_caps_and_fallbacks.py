from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator
from prometheus_client import REGISTRY


def test_allocator_cost_caps_and_fallbacks():
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
    cfg.portfolio.cost.max_slippage_bps_cap = 5.0
    # disable dynamic inputs to test fallback
    cfg.portfolio.cost.use_shadow_spread = False
    cfg.portfolio.cost.use_shadow_volume = False
    # huge k to try to exceed cap
    cfg.portfolio.cost.slippage_k_bps_per_kusd = 100.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    _ = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    snap = m._get_allocator_cost_snapshot_for_tests()
    # slippage bps must be capped at 5.0
    slip = snap["slippage_bps"].get("BTCUSDT", 0.0)
    assert slip <= 5.0



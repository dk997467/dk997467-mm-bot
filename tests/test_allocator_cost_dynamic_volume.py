from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator
from prometheus_client import REGISTRY


def test_allocator_cost_dynamic_volume_doubles_k_on_low_volume():
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
    cfg.portfolio.cost.use_shadow_spread = False
    cfg.portfolio.cost.use_shadow_volume = True
    cfg.portfolio.cost.min_volume_usd = 5000.0
    cfg.portfolio.cost.slippage_k_bps_per_kusd = 1.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # Set low volume -> doubles k
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=0.0, volume_usd=100.0, slippage_bps=0.0)
    _ = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    snap = m._get_allocator_cost_snapshot_for_tests()
    slip = snap["slippage_bps"].get("BTCUSDT", 0.0)
    # With k=1 bps per 1k and budget 10k, baseline slippage = 10; doubled k -> >= 20
    assert slip >= 20.0



from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator
from prometheus_client import REGISTRY


def test_allocator_cost_inputs_metrics_snapshot():
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
    cfg.portfolio.cost.use_shadow_volume = True
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=12.0, volume_usd=3456.0, slippage_bps=0.0)
    _ = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    snap = m._get_allocator_cost_snapshot_for_tests()
    assert snap["spread_bps"].get("BTCUSDT") == 12.0
    assert snap["volume_usd"].get("BTCUSDT") == 3456.0
    assert snap["slippage_bps"].get("BTCUSDT", 0.0) >= 0.0



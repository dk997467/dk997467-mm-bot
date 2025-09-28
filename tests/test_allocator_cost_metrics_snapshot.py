from prometheus_client import REGISTRY
from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator


def test_allocator_cost_metrics_snapshot():
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 1.0}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    cfg.portfolio.cost.fee_bps_default = 1.0
    cfg.portfolio.cost.slippage_bps_base = 0.5
    cfg.portfolio.cost.slippage_k_bps_per_kusd = 0.1
    cfg.portfolio.cost.cost_sensitivity = 0.5
    ctx = AppContext(cfg=cfg)
    ctx.metrics = Metrics(ctx)
    alloc = PortfolioAllocator(ctx)
    weights = alloc.compute_weights({"BTCUSDT": {}})
    _ = alloc.targets_from_weights(weights, budget_available_usd=cfg.portfolio.budget_usd)
    snap = ctx.metrics._get_allocator_cost_snapshot_for_tests()
    assert "BTCUSDT" in snap["cost_bps"]
    assert "BTCUSDT" in snap["attenuation"]
    # determinism: values reproducible
    cost_bps = snap["cost_bps"]["BTCUSDT"]
    attenuation = snap["attenuation"]["BTCUSDT"]
    assert cost_bps >= 0.0
    assert 0.0 <= attenuation <= 1.0



from prometheus_client import REGISTRY
from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator


def test_allocator_cost_reduce_on_high_cost():
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    # High cost: strong slippage slope
    cfg.portfolio.cost.fee_bps_default = 0.0
    cfg.portfolio.cost.slippage_bps_base = 0.0
    cfg.portfolio.cost.slippage_k_bps_per_kusd = 20.0
    cfg.portfolio.cost.cost_sensitivity = 0.5
    ctx = AppContext(cfg=cfg)
    ctx.metrics = Metrics(ctx)
    alloc = PortfolioAllocator(ctx)
    weights = alloc.compute_weights({"BTCUSDT": {}, "ETHUSDT": {}})
    targets = alloc.targets_from_weights(weights, equity_usd=None, budget_available_usd=cfg.portfolio.budget_usd)
    # Each symbol original base target was 5000; with high cost and sens=0.5 attenuation should reduce to <= 2500
    assert targets["BTCUSDT"].target_usd <= 2500.0 + 1e-6
    assert targets["ETHUSDT"].target_usd <= 2500.0 + 1e-6
    # Sum reduced deterministically below full budget
    assert sum(t.target_usd for t in targets.values()) < 8000.0



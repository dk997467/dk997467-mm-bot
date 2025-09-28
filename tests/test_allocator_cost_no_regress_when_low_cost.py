from src.common.config import AppConfig, PortfolioConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator
from prometheus_client import REGISTRY


def test_allocator_cost_no_regress_when_low_cost():
    # reset registry to avoid duplicate Gauge names across tests
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    cfg = AppConfig()
    # default cost low; ensure weights lead to near-identical targets after attenuation
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    # Low-cost regime: zero sensitivity -> no attenuation
    cfg.portfolio.cost.cost_sensitivity = 0.0
    ctx = AppContext(cfg=cfg)
    ctx.metrics = Metrics(ctx)
    alloc = PortfolioAllocator(ctx)
    weights = alloc.compute_weights({"BTCUSDT": {}, "ETHUSDT": {}})
    targets = alloc.targets_from_weights(weights, equity_usd=None, budget_available_usd=cfg.portfolio.budget_usd)
    # With low cost and sensitivity=0.5, attenuation should be close to 1.0; allow tiny deviation
    total = sum(t.target_usd for t in targets.values())
    assert abs(total - cfg.portfolio.budget_usd) < 1e-3
    # Per-symbol approximate split preserved within 1e-6 relative tolerance
    assert abs(targets["BTCUSDT"].target_usd - 6000.0) < 1e-3
    assert abs(targets["ETHUSDT"].target_usd - 4000.0) < 1e-3



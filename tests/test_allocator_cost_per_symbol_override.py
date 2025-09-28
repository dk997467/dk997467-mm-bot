from prometheus_client import REGISTRY
from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator


def test_allocator_cost_per_symbol_override():
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    # Base costs mild; override BTC with higher slippage
    cfg.portfolio.cost.fee_bps_default = 0.0
    cfg.portfolio.cost.slippage_bps_base = 0.0
    cfg.portfolio.cost.slippage_k_bps_per_kusd = 1.0
    cfg.portfolio.cost.cost_sensitivity = 0.5
    cfg.portfolio.cost.per_symbol = {
        "BTCUSDT": {
            "slippage_k_bps_per_kusd": 10.0
        }
    }
    ctx = AppContext(cfg=cfg)
    ctx.metrics = Metrics(ctx)
    alloc = PortfolioAllocator(ctx)
    weights = alloc.compute_weights({"BTCUSDT": {}, "ETHUSDT": {}})
    targets = alloc.targets_from_weights(weights, equity_usd=None, budget_available_usd=cfg.portfolio.budget_usd)
    # BTC has higher cost -> lower target than ETH
    assert targets["BTCUSDT"].target_usd < targets["ETHUSDT"].target_usd



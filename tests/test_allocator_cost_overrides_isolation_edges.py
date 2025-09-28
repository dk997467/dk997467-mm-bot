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


def test_override_isolation():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    # Override only BTC: higher k
    cfg.portfolio.cost.per_symbol = {"BTCUSDT": {"slippage_k_bps_per_kusd": 5.0}}
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=10.0, volume_usd=1000.0, slippage_bps=0.0)
    m.set_allocator_cost_inputs("ETHUSDT", spread_bps=10.0, volume_usd=1000.0, slippage_bps=0.0)
    t = alloc.targets_from_weights(cfg.portfolio.manual_weights, budget_available_usd=cfg.portfolio.budget_usd)
    assert t["BTCUSDT"].target_usd <= t["ETHUSDT"].target_usd + 1e-6


def test_isolation_under_sum_clamp():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.7, "ETHUSDT": 0.3}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    cfg.portfolio.cost.per_symbol = {"BTCUSDT": {"slippage_k_bps_per_kusd": 10.0}}
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=10.0, volume_usd=100.0, slippage_bps=0.0)
    m.set_allocator_cost_inputs("ETHUSDT", spread_bps=10.0, volume_usd=100.0, slippage_bps=0.0)
    # Force final sum clamp by small avail
    avail = 100.0
    t = alloc.targets_from_weights(cfg.portfolio.manual_weights, budget_available_usd=avail)
    # Compare shrink factors relative to pre-attenuation cap (avail*weight)
    shrink_btc = t["BTCUSDT"].target_usd / (avail * 0.7)
    shrink_eth = t["ETHUSDT"].target_usd / (avail * 0.3)
    assert shrink_btc <= shrink_eth + 1e-6



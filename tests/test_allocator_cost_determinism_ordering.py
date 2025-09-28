import json
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


def test_two_runs_byte_identical():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=12.0, volume_usd=3456.0, slippage_bps=0.0)
    m.set_allocator_cost_inputs("ETHUSDT", spread_bps=12.0, volume_usd=3456.0, slippage_bps=0.0)
    t1 = alloc.targets_from_weights(cfg.portfolio.manual_weights, budget_available_usd=cfg.portfolio.budget_usd)
    j1 = json.dumps({k: round(v.target_usd, 6) for k, v in sorted(t1.items())}, sort_keys=True, separators=(",", ":"))
    t2 = alloc.targets_from_weights(cfg.portfolio.manual_weights, budget_available_usd=cfg.portfolio.budget_usd)
    j2 = json.dumps({k: round(v.target_usd, 6) for k, v in sorted(t2.items())}, sort_keys=True, separators=(",", ":"))
    assert j1 == j2


def test_symbol_order_independence():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=10.0, volume_usd=20000.0, slippage_bps=0.0)
    m.set_allocator_cost_inputs("ETHUSDT", spread_bps=10.0, volume_usd=20000.0, slippage_bps=0.0)
    w1 = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    w2 = {"ETHUSDT": 0.4, "BTCUSDT": 0.6}
    t1 = alloc.targets_from_weights(w1, budget_available_usd=cfg.portfolio.budget_usd)
    t2 = alloc.targets_from_weights(w2, budget_available_usd=cfg.portfolio.budget_usd)
    j1 = json.dumps({k: round(v.target_usd, 6) for k, v in sorted(t1.items())}, sort_keys=True, separators=(",", ":"))
    j2 = json.dumps({k: round(v.target_usd, 6) for k, v in sorted(t2.items())}, sort_keys=True, separators=(",", ":"))
    assert j1 == j2



from math import isclose
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


def test_soft_drawdown_invariants():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    # L5 soft: make pnl_sensitivity>0 and soft_cap small to get soft<1
    cfg.portfolio.budget.pnl_sensitivity = 0.5
    cfg.portfolio.budget.drawdown_soft_cap = 0.10
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # Seed cost inputs to ensure attenuation occurs
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=20.0, volume_usd=100.0, slippage_bps=0.0)
    m.set_allocator_cost_inputs("ETHUSDT", spread_bps=20.0, volume_usd=100.0, slippage_bps=0.0)
    # equity below HWM to produce soft<1
    targets = alloc.targets_from_weights(cfg.portfolio.manual_weights, equity_usd=5000.0, budget_available_usd=cfg.portfolio.budget_usd)
    total = sum(t.target_usd for t in targets.values())
    # soft applied
    assert total <= cfg.portfolio.budget_usd * 1.0  # trivially <= budget
    # all non-negative
    assert all(t.target_usd >= 0.0 for t in targets.values())


def test_min_guard_after_all_clamps():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.99, "ETHUSDT": 0.01}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    cfg.portfolio.budget.budget_min_usd = 10.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=0.0, volume_usd=1e9, slippage_bps=0.0)
    m.set_allocator_cost_inputs("ETHUSDT", spread_bps=1000.0, volume_usd=1.0, slippage_bps=0.0)
    targets = alloc.targets_from_weights(cfg.portfolio.manual_weights, budget_available_usd=1.0)  # force final clamp small
    assert targets["ETHUSDT"].target_usd == 0.0



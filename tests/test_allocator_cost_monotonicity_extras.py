import json
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


def test_spread_monotone_non_increasing():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 1.0}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    cfg.portfolio.cost.use_shadow_spread = True
    cfg.portfolio.cost.use_shadow_volume = False
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # run with lower spread
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=5.0, volume_usd=1e9, slippage_bps=0.0)
    t1 = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    v1 = t1["BTCUSDT"].target_usd
    # run with higher spread
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=50.0, volume_usd=1e9, slippage_bps=0.0)
    t2 = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    v2 = t2["BTCUSDT"].target_usd
    assert v2 <= v1 + 1e-6


def test_volume_threshold_monotone_non_increasing():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 1.0}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    cfg.portfolio.cost.use_shadow_spread = False
    cfg.portfolio.cost.use_shadow_volume = True
    cfg.portfolio.cost.min_volume_usd = 5000.0
    cfg.portfolio.cost.slippage_k_bps_per_kusd = 5.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # high volume
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=0.0, volume_usd=6000.0, slippage_bps=0.0)
    t_hi = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    # low volume (below threshold)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=0.0, volume_usd=100.0, slippage_bps=0.0)
    t_lo = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    assert t_lo["BTCUSDT"].target_usd <= t_hi["BTCUSDT"].target_usd + 1e-6


def test_weights_input_order_invariance():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    cfg.portfolio.cost.use_shadow_spread = True
    cfg.portfolio.cost.use_shadow_volume = True
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=10.0, volume_usd=20000.0, slippage_bps=0.0)
    m.set_allocator_cost_inputs("ETHUSDT", spread_bps=10.0, volume_usd=20000.0, slippage_bps=0.0)
    # run with order1
    w1 = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    t1 = alloc.targets_from_weights(w1, budget_available_usd=cfg.portfolio.budget_usd)
    j1 = json.dumps({k: v.target_usd for k, v in sorted(t1.items())}, sort_keys=True, separators=(",", ":"))
    # run with reversed input order
    w2 = {"ETHUSDT": 0.4, "BTCUSDT": 0.6}
    t2 = alloc.targets_from_weights(w2, budget_available_usd=cfg.portfolio.budget_usd)
    j2 = json.dumps({k: v.target_usd for k, v in sorted(t2.items())}, sort_keys=True, separators=(",", ":"))
    assert j1 == j2



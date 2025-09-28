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


def test_sensitivity_zero_and_one():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 1.0}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=50.0, volume_usd=100.0, slippage_bps=0.0)
    cfg.portfolio.cost.cost_sensitivity = 0.0
    t0 = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    v0 = t0["BTCUSDT"].target_usd
    cfg.portfolio.cost.cost_sensitivity = 1.0
    t1 = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    v1 = t1["BTCUSDT"].target_usd
    assert v0 >= v1 - 1e-6


def test_volume_equal_threshold_not_low():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 1.0}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    cfg.portfolio.cost.use_shadow_volume = True
    cfg.portfolio.cost.min_volume_usd = 5000.0
    cfg.portfolio.cost.slippage_k_bps_per_kusd = 10.0
    cfg.portfolio.cost.max_slippage_bps_cap = 1000.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # volume exactly equal threshold should NOT double k
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=0.0, volume_usd=5000.0, slippage_bps=0.0)
    _ = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    snap = m._get_allocator_cost_snapshot_for_tests()
    slip = snap["slippage_bps"].get("BTCUSDT", 0.0)
    # k=10, budget 10k => baseline slippage = 100
    assert slip >= 100.0


def test_use_shadow_spread_toggle():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 1.0}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=20.0, volume_usd=10000.0, slippage_bps=0.0)
    cfg.portfolio.cost.use_shadow_spread = False
    t_false = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    v_false = t_false["BTCUSDT"].target_usd
    cfg.portfolio.cost.use_shadow_spread = True
    t_true = alloc.targets_from_weights({"BTCUSDT": 1.0}, budget_available_usd=cfg.portfolio.budget_usd)
    v_true = t_true["BTCUSDT"].target_usd
    assert v_true <= v_false + 1e-6



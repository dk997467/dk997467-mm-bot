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


def test_fallback_inputs_and_metrics():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    # Disable dynamics to force fallback
    cfg.portfolio.cost.use_shadow_spread = False
    cfg.portfolio.cost.use_shadow_volume = False
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # No inputs seeded — fallbacks used, but metrics should still be set (0)
    _ = alloc.targets_from_weights(cfg.portfolio.manual_weights, budget_available_usd=cfg.portfolio.budget_usd)
    snap = m._get_allocator_cost_snapshot_for_tests()
    # two symbols present
    # slippage present and non-negative
    assert set(snap["attenuation"].keys()) == {"BTCUSDT", "ETHUSDT"}
    assert all(v >= 0.0 for v in snap["slippage_bps"].values())


def test_metrics_cardinality_matches_universe():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    universe = {"BTCUSDT": 0.34, "ETHUSDT": 0.33, "SOLUSDT": 0.33}
    cfg.portfolio.manual_weights = universe
    cfg.portfolio.min_weight = 0.0
    cfg.portfolio.max_weight = 1.0
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)
    # set some inputs
    for s in universe.keys():
        m.set_allocator_cost_inputs(s, spread_bps=10.0, volume_usd=10000.0, slippage_bps=0.0)
    _ = alloc.targets_from_weights(universe, budget_available_usd=cfg.portfolio.budget_usd)
    snap = m._get_allocator_cost_snapshot_for_tests()
    assert set(snap["spread_bps"].keys()) == set(universe.keys())
    assert set(snap["volume_usd"].keys()) == set(universe.keys())
    assert set(snap["slippage_bps"].keys()) == set(universe.keys())



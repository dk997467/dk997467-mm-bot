from types import SimpleNamespace
from tests.e2e._utils import make_metrics_ctx
from src.portfolio.allocator import PortfolioAllocator


def _mk_ctx():
    cfg = SimpleNamespace(
        portfolio=SimpleNamespace(
            budget=SimpleNamespace(budget_min_usd=0.0),
            min_weight=0.0,
            max_weight=1.0,
            levels_per_side_min=1,
            levels_per_side_max=10,
            cost=SimpleNamespace(
                fee_bps_default=0.0,
                slippage_bps_base=0.0,
                slippage_k_bps_per_kusd=0.0,
                cost_sensitivity=0.0,
                use_shadow_spread=False,
                use_shadow_volume=False,
                min_volume_usd=0.0,
                max_slippage_bps_cap=0.0,
                fill_rate_floor=0.8,
                fill_rate_sensitivity=1.0,
                fill_rate_half_life_sec=10,
                per_symbol={},
            ),
            mode="manual",
            manual_weights={"BTC": 1.0},
            budget_usd=10000.0,
        )
    )
    return SimpleNamespace(cfg=cfg)


def test_fillrate_below_floor_reduces_targets():
    ctx = _mk_ctx()
    metrics = make_metrics_ctx()
    ctx.metrics = metrics
    alloc = PortfolioAllocator(ctx)
    alloc.set_metrics(metrics)
    # r below floor
    metrics.reset_cost_fillrate_for_tests()
    for _ in range(5):
        metrics.record_fill_event('BTC', False)
    # compute targets
    stats = {"BTC": {}}
    targets = alloc.targets_from_weights({"BTC": 1.0}, budget_available_usd=10000.0)
    t1 = targets["BTC"].target_usd
    # now r above/equal floor (simulate many fills)
    for _ in range(50):
        metrics.record_fill_event('BTC', True)
    targets2 = alloc.targets_from_weights({"BTC": 1.0}, budget_available_usd=10000.0)
    t2 = targets2["BTC"].target_usd
    assert t2 >= t1



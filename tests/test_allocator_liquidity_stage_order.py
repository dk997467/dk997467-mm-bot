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
                fill_rate_floor=1.0,
                fill_rate_sensitivity=0.0,
                fill_rate_half_life_sec=10,
                liquidity_depth_usd_target=100.0,
                liquidity_sensitivity=0.5,
                liquidity_min_floor=0.2,
                per_symbol={},
            ),
            mode="manual",
            manual_weights={"BTC": 0.6, "ETH": 0.4},
            budget_usd=10000.0,
        )
    )
    return SimpleNamespace(cfg=cfg)


def test_stage_order_and_invariants_with_liquidity():
    ctx = _mk_ctx()
    metrics = make_metrics_ctx()
    ctx.metrics = metrics
    alloc = PortfolioAllocator(ctx)
    alloc.set_metrics(metrics)

    # degrade fillrate on BTC, liquidity on BTC
    metrics.reset_cost_fillrate_for_tests()
    for _ in range(30):
        metrics.record_fill_event('BTC', False)
    for _ in range(30):
        metrics.record_fill_event('ETH', True)
    metrics.test_set_liquidity_depth('BTC', 0.0)
    metrics.test_set_liquidity_depth('ETH', 1000.0)

    # emulate drawdown softening via equity (sets soft_permille)
    alloc.targets_from_weights({"BTC": 0.6, "ETH": 0.4}, equity_usd=9000.0, budget_available_usd=8000.0)
    targets = alloc.targets_from_weights({"BTC": 0.6, "ETH": 0.4}, budget_available_usd=8000.0)
    total = sum(v.target_usd for v in targets.values())
    assert total <= 8000.0
    assert all(v.target_usd >= 0.0 for v in targets.values())



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
                liquidity_min_floor=0.6,
                per_symbol={},
            ),
            mode="manual",
            manual_weights={"BTC": 1.0},
            budget_usd=100.0,
        )
    )
    return SimpleNamespace(cfg=cfg)


def test_liquidity_factor_bounds_and_target_zero():
    ctx = _mk_ctx()
    metrics = make_metrics_ctx()
    ctx.metrics = metrics
    alloc = PortfolioAllocator(ctx)
    alloc.set_metrics(metrics)

    # target==0 => factor=1.0 regardless depth
    ctx.cfg.portfolio.cost.liquidity_depth_usd_target = 0.0
    metrics.test_set_liquidity_depth('BTC', 0.0)
    t = alloc.targets_from_weights({"BTC": 1.0}, budget_available_usd=ctx.cfg.portfolio.budget_usd)
    f = float(metrics.allocator_liquidity_factor.labels(symbol='BTC')._value.get())  # type: ignore[attr-defined]
    assert 0.0 <= f <= 1.0
    assert f == 1.0

    # with target>0 and depth=0 => factor=floor
    ctx.cfg.portfolio.cost.liquidity_depth_usd_target = 100.0
    metrics.test_set_liquidity_depth('BTC', 0.0)
    t = alloc.targets_from_weights({"BTC": 1.0}, budget_available_usd=ctx.cfg.portfolio.budget_usd)
    f = float(metrics.allocator_liquidity_factor.labels(symbol='BTC')._value.get())  # type: ignore[attr-defined]
    assert 0.6 <= f <= 1.0



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
                liquidity_depth_usd_target=0.0,
                liquidity_sensitivity=0.0,
                liquidity_min_floor=0.0,
                turnover_half_life_sec=10,
                turnover_sensitivity=1.0,
                turnover_floor=0.2,
                per_symbol={},
            ),
            mode="manual",
            manual_weights={"BTC": 0.6, "ETH": 0.4},
            budget_usd=1000.0,
        )
    )
    return SimpleNamespace(cfg=cfg)


def test_determinism_key_order_and_runs():
    ctx = _mk_ctx()
    metrics = make_metrics_ctx()
    ctx.metrics = metrics
    alloc = PortfolioAllocator(ctx)
    alloc.set_metrics(metrics)

    metrics.reset_turnover_for_tests()
    metrics.record_trade_notional('BTC', 500.0)
    metrics.record_trade_notional('ETH', 0.0)

    w1 = {"BTC": 0.6, "ETH": 0.4}
    w2 = {"ETH": 0.4, "BTC": 0.6}
    t1 = alloc.targets_from_weights(w1, budget_available_usd=ctx.cfg.portfolio.budget_usd)
    t2 = alloc.targets_from_weights(w2, budget_available_usd=ctx.cfg.portfolio.budget_usd)
    a1 = {k: v.target_usd for k, v in t1.items()}
    a2 = {k: v.target_usd for k, v in t2.items()}
    assert a1 == a2



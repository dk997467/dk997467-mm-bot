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
            manual_weights={"BTC": 0.5, "ETH": 0.5},
            budget_usd=100.0,
        )
    )
    return SimpleNamespace(cfg=cfg)


def test_per_symbol_isolation():
    ctx = _mk_ctx()
    metrics = make_metrics_ctx()
    ctx.metrics = metrics
    alloc = PortfolioAllocator(ctx)
    alloc.set_metrics(metrics)

    # Only BTC depth worsens
    metrics.test_set_liquidity_depth('BTC', 10.0)
    metrics.test_set_liquidity_depth('ETH', 100.0)
    t = alloc.targets_from_weights({"BTC": 0.5, "ETH": 0.5}, budget_available_usd=ctx.cfg.portfolio.budget_usd)
    btc = t['BTC'].target_usd
    eth = t['ETH'].target_usd
    # ETH should not increase due to BTC attenuation; any change only from final deterministic clamp
    assert btc <= eth



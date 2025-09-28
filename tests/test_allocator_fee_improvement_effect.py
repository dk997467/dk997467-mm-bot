"""
Validate that fee-aware tilt increases neutral sizing within cap when improvement exists.
"""

from types import SimpleNamespace
from unittest.mock import Mock

from src.portfolio.allocator import PortfolioAllocator
from src.common.config import AppConfig, GuardsConfig, AllocatorConfig, AllocatorSmoothingConfig
from src.common.fees import expected_tier, BYBIT_SPOT_TIERS, effective_fee_bps


def _mk_ctx(app_cfg: AppConfig, *, rolling_30d_usd: float) -> object:
    ctx = Mock()
    ctx.cfg = app_cfg
    st = SimpleNamespace()
    st.positions_by_symbol = {}
    st.color_by_symbol = {}
    ctx.state = st
    m = Mock()
    m.get_turnover_total_ewma_usd = Mock(return_value=float(rolling_30d_usd))
    ctx.metrics = m
    return ctx


def test_fee_improvement_effect_upscale_within_cap():
    # Config thresholds
    alloc_cfg = AllocatorConfig(smoothing=AllocatorSmoothingConfig(bias_cap=0.10, fee_bias_cap=0.05))
    guards_cfg = GuardsConfig()
    app_cfg = AppConfig(guards=guards_cfg, allocator=alloc_cfg)
    setattr(app_cfg, 'fees', SimpleNamespace(bybit=SimpleNamespace(distance_usd_threshold=25000.0, min_improvement_bps=0.2)))

    # Near VIP2 threshold (VIP1 now, VIP2 next)
    maker_share = 0.8
    taker_share = 0.2
    rolling = 980_000.0
    ctx = _mk_ctx(app_cfg, rolling_30d_usd=rolling)
    allocator = PortfolioAllocator(ctx)
    weights = {"BTCUSDT": 1.0, "ETHUSDT": 1.0}

    # Compute improvement precondition
    tier_now = expected_tier(rolling)
    # find next tier
    idx = 0
    for i, t in enumerate(BYBIT_SPOT_TIERS):
        if int(t.level) == int(tier_now.level):
            idx = i
            break
    tier_next = BYBIT_SPOT_TIERS[idx + 1] if idx + 1 < len(BYBIT_SPOT_TIERS) else None
    eff_now = float(effective_fee_bps(maker_share, taker_share, tier_now))
    eff_next = float(effective_fee_bps(maker_share, taker_share, tier_next)) if tier_next else eff_now
    improvement = eff_now - eff_next

    # Baseline: disable tilt via large min_improvement_bps
    app_cfg.fees.bybit.min_improvement_bps = 999.0
    base = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    sizing_in = {s: float(base[s].target_usd) for s in sorted(base.keys())}

    # Enable tilt
    app_cfg.fees.bybit.min_improvement_bps = 0.2
    out = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    sizing_out = {s: float(out[s].target_usd) for s in sorted(out.keys())}

    # Assertions
    assert improvement >= app_cfg.fees.bybit.min_improvement_bps - 1e-12
    # Total should not decrease (up-scale or equal after final clamp)
    assert sum(sizing_out.values()) >= sum(sizing_in.values()) - 1e-12
    # Per-symbol delta bounded by fee_bias_cap
    cap = float(app_cfg.allocator.smoothing.fee_bias_cap)
    for s in sizing_in.keys():
        old = sizing_in[s]
        new = sizing_out[s]
        if old != 0.0:
            rel = abs(new - old) / old
            assert rel <= cap + 1e-9


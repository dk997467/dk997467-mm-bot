"""
E2E tests for allocator fee awareness (VIP fee tiers gentle influence).
"""

from types import SimpleNamespace
from unittest.mock import Mock

from src.portfolio.allocator import PortfolioAllocator
from src.common.config import AppConfig, GuardsConfig, IntradayCapsConfig, AllocatorConfig, AllocatorSmoothingConfig, PosSkewConfig


def _mk_ctx(app_cfg: AppConfig, *, rolling_30d_usd: float) -> object:
    ctx = Mock()
    ctx.cfg = app_cfg
    st = SimpleNamespace()
    st.positions_by_symbol = {}
    st.color_by_symbol = {}
    ctx.state = st
    # Metrics mock with turnover getter
    m = Mock()
    m.get_turnover_total_ewma_usd = Mock(return_value=float(rolling_30d_usd))
    ctx.metrics = m
    return ctx


def test_case1_near_next_tier_improvement_met_tilt_within_cap_and_deterministic():
    fees_cfg = SimpleNamespace(bybit=SimpleNamespace(distance_usd_threshold=25000.0, min_improvement_bps=0.2))
    alloc_cfg = AllocatorConfig(smoothing=AllocatorSmoothingConfig(bias_cap=0.10, fee_bias_cap=0.05))
    guards_cfg = GuardsConfig()
    app_cfg = AppConfig(guards=guards_cfg, allocator=alloc_cfg)
    setattr(app_cfg, 'fees', SimpleNamespace(bybit=SimpleNamespace(distance_usd_threshold=25000.0, min_improvement_bps=0.2)))

    # VIP1 now (>=500k), next VIP2 (1M), within threshold
    ctx = _mk_ctx(app_cfg, rolling_30d_usd=980000.0)
    allocator = PortfolioAllocator(ctx)
    weights = {"BTCUSDT": 1.0, "ETHUSDT": 1.0}

    # Baseline with tilt disabled
    app_cfg.fees.bybit.min_improvement_bps = 999.0
    base = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    # Enable tilt
    app_cfg.fees.bybit.min_improvement_bps = 0.2
    out = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)

    sizing_in = {s: float(base[s].target_usd) for s in sorted(base.keys())}
    sizing_out = {s: float(out[s].target_usd) for s in sorted(out.keys())}

    assert list(sizing_out.keys()) == sorted(sizing_out.keys())
    # Total tilt up within cap
    cap = float(app_cfg.allocator.smoothing.fee_bias_cap)
    assert sum(sizing_out.values()) >= sum(sizing_in.values()) - 1e-12
    inc = 0.0
    if sum(sizing_in.values()) > 0:
        inc = (sum(sizing_out.values()) - sum(sizing_in.values())) / sum(sizing_in.values())
    assert inc <= cap + 1e-9


def test_case2_far_from_next_tier_no_tilt():
    fees_cfg = SimpleNamespace(bybit=SimpleNamespace(distance_usd_threshold=25000.0, min_improvement_bps=0.2))
    alloc_cfg = AllocatorConfig(smoothing=AllocatorSmoothingConfig(bias_cap=0.10, fee_bias_cap=0.05))
    guards_cfg = GuardsConfig()
    app_cfg = AppConfig(guards=guards_cfg, allocator=alloc_cfg)
    setattr(app_cfg, 'fees', SimpleNamespace(bybit=SimpleNamespace(distance_usd_threshold=25000.0, min_improvement_bps=0.2)))

    # Far from next tier
    ctx = _mk_ctx(app_cfg, rolling_30d_usd=100000.0)
    allocator = PortfolioAllocator(ctx)
    weights = {"BTCUSDT": 1.0, "ETHUSDT": 1.0}
    base = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    out = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    sizing_in = {s: float(base[s].target_usd) for s in sorted(base.keys())}
    sizing_out = {s: float(out[s].target_usd) for s in sorted(out.keys())}
    assert sizing_out == sizing_in


def test_case3_improvement_too_small_noop():
    fees_cfg = SimpleNamespace(bybit=SimpleNamespace(distance_usd_threshold=25000.0, min_improvement_bps=999.0))
    alloc_cfg = AllocatorConfig(smoothing=AllocatorSmoothingConfig(bias_cap=0.10, fee_bias_cap=0.05))
    guards_cfg = GuardsConfig()
    app_cfg = AppConfig(guards=guards_cfg, allocator=alloc_cfg)
    setattr(app_cfg, 'fees', SimpleNamespace(bybit=SimpleNamespace(distance_usd_threshold=25000.0, min_improvement_bps=999.0)))

    ctx = _mk_ctx(app_cfg, rolling_30d_usd=980000.0)
    allocator = PortfolioAllocator(ctx)
    weights = {"BTCUSDT": 1.0, "ETHUSDT": 1.0}
    base = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    # Explicitly set small improvement threshold
    app_cfg.fees.bybit.min_improvement_bps = 5.0
    out = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    sizing_in = {s: float(base[s].target_usd) for s in sorted(base.keys())}
    sizing_out = {s: float(out[s].target_usd) for s in sorted(out.keys())}
    assert sizing_out == sizing_in


def test_case4_coexist_with_pos_skew_bias_bounds():
    # Enable skew color breach without symbol freeze
    alloc_cfg = AllocatorConfig(smoothing=AllocatorSmoothingConfig(bias_cap=0.10, fee_bias_cap=0.05))
    guards_cfg = GuardsConfig()
    app_cfg = AppConfig(guards=guards_cfg, allocator=alloc_cfg)
    setattr(app_cfg, 'fees', SimpleNamespace(bybit=SimpleNamespace(distance_usd_threshold=25000.0, min_improvement_bps=0.2)))

    ctx = _mk_ctx(app_cfg, rolling_30d_usd=980000.0)
    # positions for color breach (sum=0.20 > 0.15), no symbol breach
    ctx.state.positions_by_symbol = {"BTCUSDT": 0.15, "ETHUSDT": 0.05}
    ctx.state.color_by_symbol = {"BTCUSDT": "blue", "ETHUSDT": "blue"}
    app_cfg.guards.pos_skew = PosSkewConfig(per_symbol_abs_limit=1.0, per_color_abs_limit=0.15)

    allocator = PortfolioAllocator(ctx)
    weights = {"BTCUSDT": 1.0, "ETHUSDT": 1.0}

    # Baseline with only skew bias (disable fee tilt)
    app_cfg.fees.bybit.min_improvement_bps = 999.0
    base = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    # Enable fee tilt
    app_cfg.fees.bybit.min_improvement_bps = 0.2
    out = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)

    cap_skew = float(app_cfg.allocator.smoothing.bias_cap)
    cap_fee = float(app_cfg.allocator.smoothing.fee_bias_cap)
    for s in sorted(base.keys()):
        b = float(base[s].target_usd)
        o = float(out[s].target_usd)
        if b > 0:
            rel = abs(o - b) / b
            # total deformation bounded by sum of caps (fee applied after skew)
            assert rel <= cap_skew + cap_fee + 1e-9


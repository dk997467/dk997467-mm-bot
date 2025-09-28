"""
E2E tests for IntradayCapsGuard integration with allocator.

Cases:
- breach on pnl -> allocator blocks
- breach on turnover -> allocator blocks
- reset at UTC midnight -> caps cleared -> allocator resumes
"""

from types import SimpleNamespace
from pathlib import Path

from unittest.mock import Mock

from src.portfolio.allocator import PortfolioAllocator
from src.common.config import AppConfig, GuardsConfig
from src.guards.intraday_caps import IntradayCapsGuard
from src.common.artifacts import export_registry_snapshot
from src.metrics.intraday_caps import IntradayCapsMetricsWriter


def _mk_ctx_with_caps(cfg: AppConfig):
    ctx = Mock()
    ctx.cfg = cfg
    st = SimpleNamespace()
    # Minimal state required by allocator
    st.positions_by_symbol = {}
    st.color_by_symbol = {}
    ctx.state = st
    # Metrics: use mock to avoid global CollectorRegistry duplication
    ctx.metrics = Mock()
    return ctx


def test_intraday_caps_breach_on_pnl_blocks_orders(tmp_path):
    # Config: enable pnl stop only
    from src.common.config import IntradayCapsConfig
    caps_cfg = IntradayCapsConfig(daily_pnl_stop=10.0, daily_turnover_cap=0.0, daily_vol_cap=0.0)
    guards_cfg = GuardsConfig(pos_skew=None if not hasattr(GuardsConfig, 'pos_skew') else getattr(GuardsConfig(), 'pos_skew'), intraday_caps=caps_cfg)  # type: ignore[arg-type]
    app_cfg = AppConfig(guards=guards_cfg)

    ctx = _mk_ctx_with_caps(app_cfg)
    # Create guard instance in state and seed breach
    guard = IntradayCapsGuard(daily_pnl_stop=10.0, daily_turnover_cap=0.0, daily_vol_cap=0.0)
    guard.reset_if_new_day("2099-01-01")
    guard.record_trade(pnl=-15.0, turnover=0.0, vol=0.0)
    ctx.state.intraday_caps_guard = guard

    allocator = PortfolioAllocator(ctx)
    weights = {"BTCUSDT": 1.0}
    targets = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    # Expect allocator to block new orders
    assert targets == {}

    # Deterministic metrics export
    writer = IntradayCapsMetricsWriter(ctx.metrics)
    writer.on_update(pnl=guard.cum_pnl, turnover=guard.cum_turnover, vol=guard.cum_vol, breached=True)
    snap = writer.snapshot()
    out = tmp_path / "metrics.json"
    export_registry_snapshot(str(out), {"intraday_caps": snap})
    data = out.read_text(encoding="utf-8")
    assert '"intraday_caps"' in data and '"breached":1' in data


def test_intraday_caps_breach_on_turnover_blocks_orders():
    from src.common.config import IntradayCapsConfig
    caps_cfg = IntradayCapsConfig(daily_pnl_stop=0.0, daily_turnover_cap=1000.0, daily_vol_cap=0.0)
    guards_cfg = GuardsConfig(pos_skew=None if not hasattr(GuardsConfig, 'pos_skew') else getattr(GuardsConfig(), 'pos_skew'), intraday_caps=caps_cfg)  # type: ignore[arg-type]
    app_cfg = AppConfig(guards=guards_cfg)

    ctx = _mk_ctx_with_caps(app_cfg)
    guard = IntradayCapsGuard(daily_pnl_stop=0.0, daily_turnover_cap=1000.0, daily_vol_cap=0.0)
    guard.reset_if_new_day("2099-01-01")
    guard.record_trade(pnl=0.0, turnover=1500.0, vol=0.0)
    ctx.state.intraday_caps_guard = guard

    allocator = PortfolioAllocator(ctx)
    weights = {"ETHUSDT": 1.0}
    targets = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    assert targets == {}


def test_intraday_caps_reset_midnight_resumes_orders():
    from src.common.config import IntradayCapsConfig
    caps_cfg = IntradayCapsConfig(daily_pnl_stop=10.0, daily_turnover_cap=1000.0, daily_vol_cap=0.0)
    guards_cfg = GuardsConfig(pos_skew=None if not hasattr(GuardsConfig, 'pos_skew') else getattr(GuardsConfig(), 'pos_skew'), intraday_caps=caps_cfg)  # type: ignore[arg-type]
    app_cfg = AppConfig(guards=guards_cfg)

    ctx = _mk_ctx_with_caps(app_cfg)
    guard = IntradayCapsGuard(daily_pnl_stop=10.0, daily_turnover_cap=1000.0, daily_vol_cap=0.0)
    guard.reset_if_new_day("2099-01-01")
    guard.record_trade(pnl=-15.0, turnover=0.0, vol=0.0)
    ctx.state.intraday_caps_guard = guard

    allocator = PortfolioAllocator(ctx)
    weights = {"BTCUSDT": 1.0}
    # Blocked before reset
    targets = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    assert targets == {}

    # Reset at UTC midnight
    guard.reset_if_new_day("2099-01-02")

    # Should resume allocations
    targets2 = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    assert targets2 != {}


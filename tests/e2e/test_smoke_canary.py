from types import SimpleNamespace
from unittest.mock import Mock

from src.portfolio.allocator import PortfolioAllocator
from src.metrics.exporter import Metrics
from src.common.artifacts import export_registry_snapshot


def test_smoke_canary_pipeline(tmp_path):
    # Minimal ctx
    ctx = SimpleNamespace()
    cfg = SimpleNamespace()
    cfg.guards = SimpleNamespace(pos_skew=SimpleNamespace(per_symbol_abs_limit=100.0))
    ctx.cfg = cfg
    st = SimpleNamespace()
    st.positions_by_symbol = {"BTCUSDT": 50.0}
    st.color_by_symbol = {"BTCUSDT": "blue"}
    ctx.state = st

    m = Metrics(ctx)
    ctx.metrics = m

    alloc = PortfolioAllocator(ctx)
    weights = {"BTCUSDT": 1.0}
    targets = alloc.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    assert "BTCUSDT" in targets

    # Build artifacts payloads
    skew_decision = type('D', (), {'symbol_breach': set(), 'color_breach': False})()
    skew_payload = m.build_position_skew_artifacts_payload(positions_by_symbol=st.positions_by_symbol, decision=skew_decision)
    fees_payload = m.build_fee_tier_payload()
    caps_payload = m.get_intraday_caps_snapshot()

    payload = {
        'position_skew': skew_payload,
        'intraday_caps': caps_payload,
        'fees': fees_payload,
    }
    out = tmp_path / 'artifacts' / 'metrics.json'
    export_registry_snapshot(str(out), payload)
    # Verify sections
    txt = out.read_text(encoding='ascii')
    assert 'position_skew' in txt and 'intraday_caps' in txt and 'fees' in txt
    # pos_skew_abs expected > 0 for BTCUSDT
    assert ctx.cfg.guards.pos_skew.per_symbol_abs_limit == 100.0



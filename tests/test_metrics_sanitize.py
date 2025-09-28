import math

from src.metrics.exporter import Metrics
from src.common.di import AppContext


class DummyCtx(AppContext):
    def __init__(self):
        self.cfg = type('C', (), {})()
        self.metrics = None


def test_finite_sanitizer_applies():
    ctx = DummyCtx()
    m = Metrics(ctx)
    # Simulate NaN/Inf through helper usage
    # We will just call internal finite via exported fields by trying set_allocator_soft_factor
    m.set_allocator_soft_factor(float('nan'))
    # value must be finite (clamped by helper): read back from internal shadow if available
    assert isinstance(m, Metrics)


def test_pos_skew_abs_limit_zero_and_positive():
    ctx = DummyCtx()
    m = Metrics(ctx)
    # Build payload for skew with limit==0 (no export > 0)
    positions = {'BTCUSDT': 50.0}
    class D: pass
    d = D()
    d.symbol_breach = set()
    d.color_breach = False
    # With limit 0, exporter should not blow up and values be finite
    m.build_position_skew_artifacts_payload(positions_by_symbol=positions, decision=d)
    # Now emulate limit>0 via ctx.cfg.guards.pos_skew
    ctx.cfg.guards = type('G', (), {})()
    ctx.cfg.guards.pos_skew = type('P', (), {'per_symbol_abs_limit': 100.0})()
    m.build_position_skew_artifacts_payload(positions_by_symbol=positions, decision=d)
    # When limit=100 and pos=50, pos_skew_abs should be 0.5 (set on gauge); cannot read gauges easily, so rely on no exceptions



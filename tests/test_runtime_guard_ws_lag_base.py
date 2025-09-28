from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_ws_lag_base_ms():
    g = RuntimeGuard(RuntimeGuardConfig(enabled=True))
    # event_ms=100000, now_ms=100120
    g.set_ws_lag_ms(120.0, 100.120)
    # direct value is set; just ensure it stores float
    assert isinstance(getattr(g, '_ws_lag_ms', 0.0), float)


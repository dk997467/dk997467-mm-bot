import time

from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_runtime_guard_basic_pause_and_recover():
    cfg = RuntimeGuardConfig(enabled=True, consecutive_breaches_to_pause=2, recovery_minutes=0.001)
    g = RuntimeGuard(cfg)
    now = time.time()
    # two consecutive breaches -> pause
    g.update({'cancel_rate_per_sec': 95.0, 'cfg_max_cancel_per_sec': 100.0, 'rest_error_rate': 0.0, 'pnl_slope_per_min': 0.0}, now)
    g.update({'cancel_rate_per_sec': 95.0, 'cfg_max_cancel_per_sec': 100.0, 'rest_error_rate': 0.02, 'pnl_slope_per_min': -0.2}, now + 0.1)
    assert g.paused is True and g.breach_streak >= 2
    # recovery after timer and no breaches
    g.update({'cancel_rate_per_sec': 1.0, 'cfg_max_cancel_per_sec': 100.0, 'rest_error_rate': 0.0, 'pnl_slope_per_min': 0.1}, now + 1.0)
    assert g.paused is False


def test_runtime_guard_reason_bitmask():
    cfg = RuntimeGuardConfig(enabled=True, consecutive_breaches_to_pause=1, recovery_minutes=10.0)
    g = RuntimeGuard(cfg)
    now = time.time()
    g.update({'cancel_rate_per_sec': 100.0, 'cfg_max_cancel_per_sec': 100.0, 'rest_error_rate': 0.02, 'pnl_slope_per_min': -0.2}, now)
    assert g.paused is True
    # 1|2|4 == 7
    assert int(getattr(g, 'last_reason_mask', 0)) == 7


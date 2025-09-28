from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_runtime_guard_reject_rate_pause():
    cfg = RuntimeGuardConfig(enabled=True, consecutive_breaches_to_pause=1, recovery_minutes=10.0, order_reject_rate_max=0.3)
    g = RuntimeGuard(cfg)
    for _ in range(2):
        g.on_send_ok()
    for _ in range(2):
        g.on_reject()
    now = 1000.0
    g.update({'cancel_rate_per_sec': 0.0, 'cfg_max_cancel_per_sec': 100.0, 'rest_error_rate': 0.0, 'pnl_slope_per_min': 0.0}, now)
    assert g.paused is True


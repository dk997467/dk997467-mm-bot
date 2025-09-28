from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_hysteresis_pause_and_resume():
    cfg = RuntimeGuardConfig(
        enabled=True,
        hysteresis_bad_required=2,
        hysteresis_good_required=2,
        recovery_minutes=0.0,
        order_reject_rate_max=0.1,
        window_seconds=0.5,
    )
    g = RuntimeGuard(cfg)
    # bad: high reject rate
    g.on_reject("A", 0.0)
    g.on_reject("B", 0.1)
    g.update({'cancel_rate_per_sec':0.0,'cfg_max_cancel_per_sec':1.0,'rest_error_rate':0.0,'pnl_slope_per_min':0.0}, 0.05)
    g.update({'cancel_rate_per_sec':0.0,'cfg_max_cancel_per_sec':1.0,'rest_error_rate':0.0,'pnl_slope_per_min':0.0}, 0.1)
    assert g.paused is True
    last_reason = getattr(g, 'last_reason_mask', 0)
    assert last_reason != 0
    last_ts = getattr(g, 'last_change_ts', 0.0)
    assert last_ts > 0.0
    # good: no breaches for two steps
    g.on_send_ok("C", 1.0)
    g.on_send_ok("D", 1.1)
    g.update({'cancel_rate_per_sec':0.0,'cfg_max_cancel_per_sec':1.0,'rest_error_rate':0.0,'pnl_slope_per_min':0.0}, 1.1)
    g.update({'cancel_rate_per_sec':0.0,'cfg_max_cancel_per_sec':1.0,'rest_error_rate':0.0,'pnl_slope_per_min':0.0}, 1.2)
    assert g.paused is False


from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_runtime_guard_latency_ws_rejects():
    cfg = RuntimeGuardConfig(
        enabled=True,
        consecutive_breaches_to_pause=1,
        recovery_minutes=10.0,
        cancel_p95_ms_max=50.0,
        ws_lag_ms_max=10.0,
        order_reject_rate_max=0.2,
    )
    g = RuntimeGuard(cfg)
    # add cancel samples: p95 ~ 60 -> breach
    for ms in [10, 20, 30, 60, 80]:
        g.add_cancel_latency_sample(ms)
    g.set_ws_lag_ms(15.0)  # breach
    # reject rate 2/5 = 0.4 -> breach
    for i in range(3):
        g.on_send_ok()
    for i in range(2):
        g.on_reject()
    reason = g.evaluate()
    assert reason != 0


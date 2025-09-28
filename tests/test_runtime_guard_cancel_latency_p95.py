from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_cancel_latency_p95_clip_and_window():
    cfg = RuntimeGuardConfig(enabled=True, window_seconds=10, max_cancel_latency_ms_p95=60000)
    g = RuntimeGuard(cfg)
    # samples at t=0
    for ms in [10, 20, 30000, 120000]:
        g.add_cancel_latency_sample(ms, 0.0)
    p95 = g.compute_p95_cancel_latency(0.0)
    # values become [10,20,30000,60000] -> idx=int(0.95*(4-1))=int(2.85)=2 -> 30000
    assert int(p95) == 30000
    # move time beyond window
    p95_late = g.compute_p95_cancel_latency(20.0)
    assert p95_late == 0.0


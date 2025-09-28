from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_reject_rate_window_and_dedup():
    cfg = RuntimeGuardConfig(enabled=True, window_seconds=5, order_reject_rate_max=1.0)
    g = RuntimeGuard(cfg)
    # t=0 reject A
    g.on_reject("A", 0.0)
    # t=1 duplicate reject A (ignored)
    g.on_reject("A", 1.0)
    # t=2 ok B
    g.on_send_ok("B", 2.0)
    rate = g.compute_reject_rate(2.0)
    assert abs(rate - 0.5) < 1e-9

    # t=6 evict window
    rate2 = g.compute_reject_rate(6.0)
    assert rate2 == 0.0

    # retry case: reject then ok for same cid -> only first counts
    g.on_reject("C", 0.0)
    g.on_send_ok("C", 0.5)
    rate3 = g.compute_reject_rate(1.0)
    assert abs(rate3 - 1.0) < 1e-9


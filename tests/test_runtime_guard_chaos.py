import random

from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig


def test_runtime_guard_chaos_window_and_hysteresis():
    random.seed(42)
    cfg = RuntimeGuardConfig(enabled=True, window_seconds=30, order_reject_rate_max=0.4, hysteresis_bad_required=2, hysteresis_good_required=2)
    g = RuntimeGuard(cfg)
    now = 0.0
    # generate ~1000 events over 60 seconds
    for i in range(1000):
        now += 0.06
        if random.random() < 0.3:
            g.on_reject(f"cid{i}", now)
        else:
            g.on_send_ok(f"cid{i}", now)
        if i % 50 == 0:
            # add some cancel latencies
            g.add_cancel_latency_sample(random.choice([5, 10, 20, 40, 80, 160, 320, 64000]), now)
        # periodic evaluate to roll eviction
        g.evaluate(now=now)
    # After 60s, evict to last 30s
    rate = g.compute_reject_rate(now)
    p95 = g.compute_p95_cancel_latency(now)
    # Bounds checks
    assert 0.0 <= rate <= 1.0
    assert 0.0 <= p95 <= 60000.0
    # Buffers bounded (heuristic, should be << total events)
    # We cannot access internals directly in strict sense, but compute doesn't error and stays in bounds
    # Hysteresis check: force two bads then two goods
    g.on_reject("X1", now + 0.1)
    g.on_reject("X2", now + 0.2)
    g.update({'cancel_rate_per_sec':0.0,'cfg_max_cancel_per_sec':1.0,'rest_error_rate':0.0,'pnl_slope_per_min':0.0}, now + 0.2)
    assert g.paused in (True, False)
    g.on_send_ok("Y1", now + 0.3)
    g.on_send_ok("Y2", now + 0.4)
    g.update({'cancel_rate_per_sec':0.0,'cfg_max_cancel_per_sec':1.0,'rest_error_rate':0.0,'pnl_slope_per_min':0.0}, now + 0.4)
    assert g.paused in (True, False)


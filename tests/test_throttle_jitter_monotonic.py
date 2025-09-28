import time
from src.guards.throttle import ThrottleGuard
from src.common.config import ThrottleConfig


def test_jitter_monotonic_bucket():
    cfg = ThrottleConfig(
        backoff_base_ms=100,
        backoff_max_ms=5000,
        backoff_cap_ms=5000.0,
        jitter_pct=0.10,
        error_rate_trigger=0.0,
        ws_lag_trigger_ms=0.0,
    )
    g = ThrottleGuard(cfg)
    sym = 'XBTUSD'
    now = time.time()
    # Same bucket: identical jittered values if base is same
    b1 = g.compute_backoff_ms(1.0, 1000.0, now, sym)
    g2 = ThrottleGuard(cfg)
    b2 = g2.compute_backoff_ms(1.0, 1000.0, now, sym)
    assert b1 == b2
    # Always within cap and +/-10% around nominal
    assert 0 <= b1 <= 5000
    base = min(cfg.backoff_max_ms, cfg.backoff_base_ms)  # first step
    assert abs(b1 - base) <= int(base * cfg.jitter_pct) + 5


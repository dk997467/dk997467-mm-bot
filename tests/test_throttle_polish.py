import time
from src.guards.throttle import ThrottleGuard
from src.common.config import ThrottleConfig


def test_no_double_count_on_block():
    cfg = ThrottleConfig(window_sec=2.0, max_creates_per_sec=0.5, per_symbol=True)
    g = ThrottleGuard(cfg)
    now = time.time()
    # blocked path: do NOT call on_event
    assert not g.get_events_in_window('BTCUSDT', now).get('create', 0)
    # simulate a successful REST call
    g.on_event('create', 'BTCUSDT', now)
    assert g.get_events_in_window('BTCUSDT', now).get('create', 0) == 1


def test_cap_and_jitter_deterministic():
    cfg = ThrottleConfig(
        backoff_base_ms=200,
        backoff_max_ms=5000,
        backoff_cap_ms=5000.0,
        jitter_pct=0.10,
        error_rate_trigger=0.0,
        ws_lag_trigger_ms=0.0,
    )
    g = ThrottleGuard(cfg)
    now = time.time()
    sym = 'BTCUSDT'
    # multiple steps to grow
    b1 = g.compute_backoff_ms(1.0, 1000.0, now, sym)
    b2 = g.compute_backoff_ms(1.0, 1000.0, now + 1, sym)
    b3 = g.compute_backoff_ms(1.0, 1000.0, now + 2, sym)
    assert b1 >= 0 and b2 >= 0 and b3 >= 0
    assert b3 <= 5000
    # deterministic for same bucket
    bucket_now = int(now // 5)
    b_same = g.compute_backoff_ms(1.0, 1000.0, now, sym)
    assert b_same == b1


def test_events_eviction_and_gauge_counts():
    cfg = ThrottleConfig(window_sec=1.0, max_creates_per_sec=10.0, per_symbol=True)
    g = ThrottleGuard(cfg)
    now = time.time()
    for i in range(3):
        g.on_event('create', 'ETHUSDT', now + i * 0.2)
    cnt = g.get_events_in_window('ETHUSDT', now + 0.6)['create']
    assert cnt >= 2
    # after eviction window
    cnt2 = g.get_events_in_window('ETHUSDT', now + 2.0)['create']
    assert cnt2 == 0



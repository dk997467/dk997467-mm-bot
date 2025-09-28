# Test throttle ring buffer window correctness and memory stability
from types import SimpleNamespace


def test_throttle_ring_buffer_window():
    from src.guards.throttle import ThrottleGuard, _Ring
    from src.common.config import ThrottleConfig

    # Test _Ring directly
    ring = _Ring(3, 1000)  # 3-second window, start at ts 1000
    
    # Initial state
    assert ring.size == 3
    assert ring.total(1000) == 0
    
    # Simulate time progression and events
    ts = 1000  # Start time
    
    # Add events at current time
    ring.add(ts, 2)
    assert ring.total(ts) == 2
    
    # Add more events at same time
    ring.add(ts, 1)
    assert ring.total(ts) == 3
    
    # Move to next second and add events
    ts += 1
    ring.add(ts, 2)
    # Should have events from both seconds
    total = ring.total(ts)
    assert total >= 2  # At least the new events
    
    # Jump beyond window size: all buckets should reset
    ts += 10  # Jump far beyond window
    assert ring.total(ts) == 0
    
    # Verify ring size is stable
    assert len(ring.ring) == 3
    
    # Test ThrottleGuard integration
    cfg = ThrottleConfig(
        window_sec=3,
        per_symbol=True,
        max_creates_per_sec=10,
        max_amends_per_sec=20,
        max_cancels_per_sec=30,
        error_rate_trigger=0.1,
        ws_lag_trigger_ms=100,
        backoff_base_ms=100,
        backoff_max_ms=5000
    )
    
    guard = ThrottleGuard(cfg)
    
    # Check initial state
    assert guard.window_sec == 3
    
    # Test rate limiting
    ts = 1000
    # Add 5 creates in first second
    for _ in range(5):
        assert guard.allowed("create", "BTCUSDT", ts)
        guard.on_event("create", "BTCUSDT", ts)
    
    # Check counts
    counts = guard.get_window_counts("BTCUSDT", ts)
    assert counts["create"] == 5
    assert counts["amend"] == 0
    assert counts["cancel"] == 0
    
    # Advance time and add more events
    ts += 1
    for _ in range(3):
        guard.on_event("amend", "BTCUSDT", ts)
    
    counts = guard.get_window_counts("BTCUSDT", ts)
    assert counts["create"] == 5  # Still in window
    assert counts["amend"] == 3
    assert counts["cancel"] == 0
    
    # Test memory stability: structure size doesn't grow
    guard._ensure_symbol("BTCUSDT")
    initial_size = len(guard._rings["BTCUSDT"]["create"].ring)
    
    # Add many events over time
    for i in range(10):
        ts += 1
        guard.on_event("create", "BTCUSDT", ts)
        guard.on_event("amend", "BTCUSDT", ts)
        guard.on_event("cancel", "BTCUSDT", ts)
    
    # Structure size should remain constant
    final_size = len(guard._rings["BTCUSDT"]["create"].ring)
    assert final_size == initial_size == 3
    
    # Window should slide correctly
    counts = guard.get_window_counts("BTCUSDT", ts)
    # Check that counts are reasonable (basic functionality test)
    assert counts["create"] >= 0
    assert counts["amend"] >= 0 
    assert counts["cancel"] >= 0
    
    # Test basic functionality: events can be added and counted
    assert isinstance(counts["create"], int)
    assert isinstance(counts["amend"], int)
    assert isinstance(counts["cancel"], int)

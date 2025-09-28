"""Tests for throttle window rate limiting."""

import time
from src.guards.throttle import ThrottleGuard
from src.common.config import ThrottleConfig


def test_throttle_window_basic():
    """Test basic rate limiting in window."""
    cfg = ThrottleConfig(
        window_sec=10.0,
        max_creates_per_sec=2.0,  # 20 creates in 10s window
        per_symbol=False
    )
    guard = ThrottleGuard(cfg)
    
    now = time.time()
    
    # Allow first 20 creates
    for i in range(20):
        assert guard.allowed('create', 'BTCUSDT', now + i * 0.1)
        guard.on_event('create', 'BTCUSDT', now + i * 0.1)
    
    # 21st should be blocked
    assert not guard.allowed('create', 'BTCUSDT', now + 2.0)
    
    # After window expires, should allow again
    assert guard.allowed('create', 'BTCUSDT', now + 11.0)


def test_throttle_window_per_symbol():
    """Test per-symbol rate limiting."""
    cfg = ThrottleConfig(
        window_sec=5.0,
        max_creates_per_sec=1.0,  # 5 creates per symbol in 5s window
        per_symbol=True
    )
    guard = ThrottleGuard(cfg)
    
    now = time.time()
    
    # Fill up BTCUSDT limit
    for i in range(5):
        assert guard.allowed('create', 'BTCUSDT', now + i * 0.1)
        guard.on_event('create', 'BTCUSDT', now + i * 0.1)
    
    # BTCUSDT should be blocked
    assert not guard.allowed('create', 'BTCUSDT', now + 1.0)
    
    # ETHUSDT should still be allowed
    assert guard.allowed('create', 'ETHUSDT', now + 1.0)
    guard.on_event('create', 'ETHUSDT', now + 1.0)


def test_throttle_window_eviction():
    """Test that old events are evicted from window."""
    cfg = ThrottleConfig(
        window_sec=2.0,
        max_creates_per_sec=1.0,  # 2 creates in 2s window
        per_symbol=False
    )
    guard = ThrottleGuard(cfg)
    
    now = time.time()
    
    # Fill window at start
    assert guard.allowed('create', 'BTCUSDT', now)
    guard.on_event('create', 'BTCUSDT', now)
    assert guard.allowed('create', 'BTCUSDT', now + 0.5)
    guard.on_event('create', 'BTCUSDT', now + 0.5)
    
    # Should be blocked
    assert not guard.allowed('create', 'BTCUSDT', now + 1.0)
    
    # After window moves, old events evicted
    assert guard.allowed('create', 'BTCUSDT', now + 2.5)


def test_throttle_different_kinds():
    """Test that different operation types have separate limits."""
    cfg = ThrottleConfig(
        window_sec=5.0,
        max_creates_per_sec=1.0,  # 5 creates
        max_amends_per_sec=2.0,   # 10 amends
        max_cancels_per_sec=3.0,  # 15 cancels
        per_symbol=False
    )
    guard = ThrottleGuard(cfg)
    
    now = time.time()
    
    # Fill creates
    for i in range(5):
        assert guard.allowed('create', 'BTCUSDT', now + i * 0.1)
        guard.on_event('create', 'BTCUSDT', now + i * 0.1)
    
    # Creates blocked, but amends still allowed
    assert not guard.allowed('create', 'BTCUSDT', now + 1.0)
    assert guard.allowed('amend', 'BTCUSDT', now + 1.0)
    assert guard.allowed('cancel', 'BTCUSDT', now + 1.0)

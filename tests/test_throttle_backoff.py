"""Tests for adaptive backoff in throttle guard."""

import time
from src.guards.throttle import ThrottleGuard
from src.common.config import ThrottleConfig


def test_backoff_on_error_rate():
    """Test backoff when error rate exceeds trigger."""
    cfg = ThrottleConfig(
        backoff_base_ms=100,
        backoff_max_ms=1000,
        error_rate_trigger=0.01,
        ws_lag_trigger_ms=1000
    )
    guard = ThrottleGuard(cfg)
    
    now = time.time()
    
    # No backoff when error rate is low
    backoff = guard.compute_backoff_ms(0.005, 100.0, now)
    assert backoff == 0
    
    # Backoff when error rate exceeds trigger
    backoff = guard.compute_backoff_ms(0.02, 100.0, now + 1)
    assert backoff == 100
    
    # Exponential growth
    backoff = guard.compute_backoff_ms(0.03, 100.0, now + 2)
    assert backoff == 200
    
    # Capped at max
    for i in range(10):
        backoff = guard.compute_backoff_ms(0.05, 100.0, now + 3 + i)
    assert backoff <= 1000


def test_backoff_on_ws_lag():
    """Test backoff when WS lag exceeds trigger."""
    cfg = ThrottleConfig(
        backoff_base_ms=200,
        backoff_max_ms=2000,
        error_rate_trigger=0.1,
        ws_lag_trigger_ms=300
    )
    guard = ThrottleGuard(cfg)
    
    now = time.time()
    
    # No backoff when lag is low
    backoff = guard.compute_backoff_ms(0.001, 200.0, now)
    assert backoff == 0
    
    # Backoff when lag exceeds trigger
    backoff = guard.compute_backoff_ms(0.001, 400.0, now + 1)
    assert backoff == 200


def test_backoff_reset():
    """Test that backoff resets when conditions normalize."""
    cfg = ThrottleConfig(
        backoff_base_ms=100,
        backoff_max_ms=1000,
        error_rate_trigger=0.01,
        ws_lag_trigger_ms=500
    )
    guard = ThrottleGuard(cfg)
    
    now = time.time()
    
    # Build up backoff
    guard.compute_backoff_ms(0.02, 100.0, now)
    guard.compute_backoff_ms(0.02, 100.0, now + 1)
    backoff = guard.compute_backoff_ms(0.02, 100.0, now + 2)
    assert backoff > 100
    
    # Conditions normalize - backoff should reset
    backoff = guard.compute_backoff_ms(0.005, 100.0, now + 3)
    assert backoff == 0


def test_backoff_combined_triggers():
    """Test backoff when both error rate and WS lag trigger."""
    cfg = ThrottleConfig(
        backoff_base_ms=50,
        backoff_max_ms=500,
        error_rate_trigger=0.01,
        ws_lag_trigger_ms=200
    )
    guard = ThrottleGuard(cfg)
    
    now = time.time()
    
    # Either trigger should cause backoff
    backoff1 = guard.compute_backoff_ms(0.02, 100.0, now)
    assert backoff1 == 50
    
    backoff2 = guard.compute_backoff_ms(0.005, 300.0, now + 1)
    assert backoff2 == 100
    
    # Both triggers together
    backoff3 = guard.compute_backoff_ms(0.03, 400.0, now + 2)
    assert backoff3 == 200

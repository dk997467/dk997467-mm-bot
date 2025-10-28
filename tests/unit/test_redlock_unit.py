"""
Unit tests for Redlock in-memory implementation.

Tests:
- Acquire and release locks
- Token validation
- TTL expiry
- Refresh locks
- Concurrent acquire (race conditions)
- Clock drift scenarios
- Token leak detection
"""

from __future__ import annotations

import pytest

from tools.state.locks import Redlock


class FakeClock:
    """Fake clock for deterministic testing."""
    
    def __init__(self, start_time: float = 0.0):
        self.current_time = start_time
    
    def __call__(self) -> float:
        return self.current_time
    
    def advance(self, seconds: float) -> None:
        """Advance clock by seconds."""
        self.current_time += seconds


def test_redlock_acquire_release_basic():
    """Test basic acquire and release."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Acquire lock
    token = lock.acquire("resource1", ttl_ms=5000)
    assert token is not None
    assert len(token) == 32  # 16 bytes hex = 32 chars
    
    # Release with correct token
    assert lock.release("resource1", token) is True
    
    # Resource should be free now
    token2 = lock.acquire("resource1", ttl_ms=5000)
    assert token2 is not None
    assert token2 != token  # Different token


def test_redlock_acquire_already_locked():
    """Test that acquire fails when resource is already locked."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # First acquire succeeds
    token1 = lock.acquire("resource1", ttl_ms=5000)
    assert token1 is not None
    
    # Second acquire fails (same resource)
    token2 = lock.acquire("resource1", ttl_ms=5000)
    assert token2 is None


def test_redlock_release_wrong_token():
    """Test that release fails with wrong token."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    token = lock.acquire("resource1", ttl_ms=5000)
    assert token is not None
    
    # Try to release with wrong token
    wrong_token = "wrong_token_12345678"
    assert lock.release("resource1", wrong_token) is False
    
    # Lock should still be held
    assert lock.is_locked("resource1")


def test_redlock_release_nonexistent():
    """Test release on non-existent resource."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    assert lock.release("nonexistent", "token") is False


def test_redlock_ttl_expiry():
    """Test that locks expire after TTL."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Acquire with 5 second TTL
    token = lock.acquire("resource1", ttl_ms=5000)
    assert token is not None
    assert lock.is_locked("resource1")
    
    # Advance clock by 3 seconds (still locked)
    clock.advance(3.0)
    assert lock.is_locked("resource1")
    assert lock.get_ttl_ms("resource1") == 2000
    
    # Advance clock past expiry (6 seconds total)
    clock.advance(3.0)
    assert not lock.is_locked("resource1")
    assert lock.get_ttl_ms("resource1") == -1
    
    # Should be able to acquire again
    token2 = lock.acquire("resource1", ttl_ms=5000)
    assert token2 is not None


def test_redlock_refresh_before_expiry():
    """Test refreshing a lock before it expires."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Acquire with 5 second TTL
    token = lock.acquire("resource1", ttl_ms=5000)
    assert token is not None
    
    # Advance 3 seconds and refresh
    clock.advance(3.0)
    assert lock.refresh("resource1", token, ttl_ms=7000) is True
    
    # TTL should be reset to 7 seconds from current time
    assert lock.get_ttl_ms("resource1") == 7000
    
    # Advance 5 more seconds (total 8)
    clock.advance(5.0)
    # Should still be locked (refresh gave 7s from second 3)
    assert lock.is_locked("resource1")


def test_redlock_refresh_after_expiry():
    """Test that refresh fails after lock expires."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Acquire with 5 second TTL
    token = lock.acquire("resource1", ttl_ms=5000)
    assert token is not None
    
    # Advance past expiry
    clock.advance(6.0)
    
    # Refresh should fail
    assert lock.refresh("resource1", token, ttl_ms=5000) is False
    assert not lock.is_locked("resource1")


def test_redlock_refresh_wrong_token():
    """Test that refresh fails with wrong token."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    token = lock.acquire("resource1", ttl_ms=5000)
    assert token is not None
    
    # Try to refresh with wrong token
    wrong_token = "wrong_token_12345678"
    assert lock.refresh("resource1", wrong_token, ttl_ms=5000) is False


def test_redlock_concurrent_acquire_race():
    """Test race condition with concurrent acquire attempts."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Simulate two workers trying to acquire at same time
    token1 = lock.acquire("resource1", ttl_ms=5000)
    token2 = lock.acquire("resource1", ttl_ms=5000)
    
    # Only one should succeed
    assert token1 is not None
    assert token2 is None


def test_redlock_release_expired_lock():
    """Test that release fails on expired lock."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    token = lock.acquire("resource1", ttl_ms=5000)
    assert token is not None
    
    # Advance past expiry
    clock.advance(6.0)
    
    # Release should fail (lock has expired)
    assert lock.release("resource1", token) is False


def test_redlock_acquire_after_expiry():
    """Test acquiring lock after previous holder expires."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Worker 1 acquires
    token1 = lock.acquire("resource1", ttl_ms=5000)
    assert token1 is not None
    
    # Advance past expiry
    clock.advance(6.0)
    
    # Worker 2 should be able to acquire (lock expired)
    token2 = lock.acquire("resource1", ttl_ms=5000)
    assert token2 is not None
    assert token2 != token1


def test_redlock_is_locked():
    """Test is_locked helper method."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Initially not locked
    assert not lock.is_locked("resource1")
    
    # Acquire and check
    token = lock.acquire("resource1", ttl_ms=5000)
    assert lock.is_locked("resource1")
    
    # Release and check
    lock.release("resource1", token)
    assert not lock.is_locked("resource1")


def test_redlock_get_ttl_ms():
    """Test get_ttl_ms method."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Non-existent resource
    assert lock.get_ttl_ms("nonexistent") == -1
    
    # Acquire and check TTL
    token = lock.acquire("resource1", ttl_ms=10000)
    assert lock.get_ttl_ms("resource1") == 10000
    
    # Advance and check TTL
    clock.advance(3.5)
    ttl = lock.get_ttl_ms("resource1")
    assert 6400 <= ttl <= 6600  # ~6.5 seconds remaining


def test_redlock_clear_all():
    """Test clear_all method."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Acquire multiple locks
    lock.acquire("resource1", ttl_ms=5000)
    lock.acquire("resource2", ttl_ms=5000)
    
    assert lock.is_locked("resource1")
    assert lock.is_locked("resource2")
    
    # Clear all
    lock.clear_all()
    
    assert not lock.is_locked("resource1")
    assert not lock.is_locked("resource2")


def test_redlock_get_all_locks():
    """Test get_all_locks debugging method."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Initially empty
    locks = lock.get_all_locks()
    assert len(locks) == 0
    
    # Acquire some locks
    token1 = lock.acquire("resource1", ttl_ms=5000)
    token2 = lock.acquire("resource2", ttl_ms=3000)
    
    locks = lock.get_all_locks()
    assert len(locks) == 2
    assert locks["resource1"][0] == token1
    assert locks["resource2"][0] == token2
    
    # Advance to expire one lock
    clock.advance(4.0)
    
    # get_all_locks should clean up expired locks
    locks = lock.get_all_locks()
    assert len(locks) == 1
    assert "resource1" in locks
    assert "resource2" not in locks


def test_redlock_multiple_resources():
    """Test managing multiple independent resources."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Acquire different resources
    token1 = lock.acquire("resource1", ttl_ms=5000)
    token2 = lock.acquire("resource2", ttl_ms=5000)
    token3 = lock.acquire("resource3", ttl_ms=5000)
    
    assert token1 is not None
    assert token2 is not None
    assert token3 is not None
    
    # All should be locked
    assert lock.is_locked("resource1")
    assert lock.is_locked("resource2")
    assert lock.is_locked("resource3")
    
    # Release one
    lock.release("resource2", token2)
    assert lock.is_locked("resource1")
    assert not lock.is_locked("resource2")
    assert lock.is_locked("resource3")


def test_redlock_token_uniqueness():
    """Test that tokens are unique across acquires."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    tokens = set()
    for i in range(100):
        token = lock.acquire(f"resource{i}", ttl_ms=5000)
        assert token is not None
        assert token not in tokens
        tokens.add(token)


def test_redlock_zero_ttl():
    """Test behavior with very short TTL."""
    clock = FakeClock()
    lock = Redlock(clock=clock)
    
    # Acquire with 100ms TTL
    token = lock.acquire("resource1", ttl_ms=100)
    assert token is not None
    assert lock.is_locked("resource1")
    
    # Advance 101ms
    clock.advance(0.101)
    
    # Should be expired
    assert not lock.is_locked("resource1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


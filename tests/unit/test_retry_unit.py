"""
Unit tests for deterministic retry mechanism.

Tests:
- Basic retry with success
- Retry exhaustion (all attempts fail)
- Exponential backoff calculation
- Deterministic jitter
- Timeout handling
- retry_with_log variant
"""

from __future__ import annotations

import pytest

from tools.common.retry import retry, retry_with_log, _pseudo_jitter


class FakeClock:
    """Fake clock for deterministic testing."""
    
    def __init__(self, start_time: float = 0.0):
        self.current_time = start_time
    
    def __call__(self) -> float:
        return self.current_time
    
    def advance(self, seconds: float) -> None:
        """Advance clock by seconds."""
        self.current_time += seconds


class FailNTimes:
    """Callable that fails N times then succeeds."""
    
    def __init__(self, fail_count: int, success_value: str = "success"):
        self.fail_count = fail_count
        self.success_value = success_value
        self.attempts = 0
    
    def __call__(self):
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise ValueError(f"Attempt {self.attempts} failed")
        return self.success_value


def test_retry_success_first_attempt():
    """Test immediate success on first attempt."""
    def always_succeed():
        return "success"
    
    result = retry(always_succeed, attempts=3, base_ms=100, jitter_off=True)
    assert result == "success"


def test_retry_success_after_failures():
    """Test success after some failures."""
    clock = FakeClock()
    call = FailNTimes(fail_count=2, success_value="finally")
    
    result = retry(
        call,
        attempts=5,
        base_ms=100,
        jitter_off=True,
        deterministic_clock=clock,
    )
    
    assert result == "finally"
    assert call.attempts == 3  # Failed 2 times, succeeded on 3rd


def test_retry_all_attempts_fail():
    """Test that last exception is raised when all attempts fail."""
    call = FailNTimes(fail_count=10, success_value="never")
    
    with pytest.raises(ValueError, match="Attempt 3 failed"):
        retry(call, attempts=3, base_ms=100, jitter_off=True)
    
    assert call.attempts == 3


def test_retry_exponential_backoff():
    """Test exponential backoff calculation (without actual sleep)."""
    clock = FakeClock()
    call = FailNTimes(fail_count=3)
    
    # With jitter_off=True, backoff should be: base * 2^(attempt-1)
    # Attempt 1: fail, wait 100ms
    # Attempt 2: fail, wait 200ms
    # Attempt 3: fail, wait 400ms
    # Attempt 4: success
    
    result = retry(
        call,
        attempts=5,
        base_ms=100,
        jitter_off=True,
        deterministic_clock=clock,
    )
    
    assert result == "success"
    assert call.attempts == 4


def test_retry_deterministic_jitter():
    """Test that jitter is deterministic based on idem_key."""
    # Same idem_key should produce same jitter
    jitter1_a1 = _pseudo_jitter("key1", attempt=1)
    jitter1_a1_again = _pseudo_jitter("key1", attempt=1)
    assert jitter1_a1 == jitter1_a1_again
    
    # Different idem_key should produce different jitter
    jitter2_a1 = _pseudo_jitter("key2", attempt=1)
    assert jitter1_a1 != jitter2_a1
    
    # Same key, different attempt should produce different jitter
    jitter1_a2 = _pseudo_jitter("key1", attempt=2)
    assert jitter1_a1 != jitter1_a2
    
    # Jitter should be in range [0, 1]
    assert 0.0 <= jitter1_a1 <= 1.0
    assert 0.0 <= jitter2_a1 <= 1.0


def test_retry_with_jitter():
    """Test retry with jitter enabled."""
    clock = FakeClock()
    call = FailNTimes(fail_count=2)
    
    # With jitter, delay should be: base * 2^(attempt-1) * (1 + jitter * 0.5)
    result = retry(
        call,
        attempts=5,
        base_ms=100,
        jitter_off=False,
        idem_key="test_key",
        deterministic_clock=clock,
    )
    
    assert result == "success"
    assert call.attempts == 3


def test_retry_timeout():
    """Test timeout handling."""
    clock = FakeClock()
    
    def slow_fail():
        clock.advance(0.5)  # Each attempt takes 500ms
        raise ValueError("Failed")
    
    # Timeout after 1 second
    with pytest.raises(TimeoutError, match="Retry timeout"):
        retry(
            slow_fail,
            attempts=10,
            base_ms=100,
            jitter_off=True,
            deterministic_clock=clock,
            timeout_ms=1000,
        )


def test_retry_timeout_before_first_attempt():
    """Test timeout check before first attempt (timeout_ms=0)."""
    clock = FakeClock()
    
    def dummy():
        return "never"
    
    with pytest.raises(TimeoutError, match="Retry timeout"):
        retry(
            dummy,
            attempts=5,
            base_ms=100,
            jitter_off=True,
            deterministic_clock=clock,
            timeout_ms=0,  # Immediate timeout (0ms)
        )


def test_retry_invalid_attempts():
    """Test that attempts < 1 raises ValueError."""
    def dummy():
        return "never"
    
    with pytest.raises(ValueError, match="attempts must be >= 1"):
        retry(dummy, attempts=0)
    
    with pytest.raises(ValueError, match="attempts must be >= 1"):
        retry(dummy, attempts=-1)


def test_retry_with_log():
    """Test retry_with_log variant."""
    clock = FakeClock()
    call = FailNTimes(fail_count=2, success_value="logged")
    
    log_calls = []
    
    def log_fn(message: str, attempt: int, exception: Exception):
        log_calls.append((message, attempt, str(exception)))
    
    result = retry_with_log(
        call,
        attempts=5,
        base_ms=100,
        jitter_off=True,
        deterministic_clock=clock,
        log_fn=log_fn,
    )
    
    assert result == "logged"
    assert len(log_calls) == 2  # Two failures logged
    assert log_calls[0][1] == 1
    assert log_calls[1][1] == 2
    assert "Attempt 1/5 failed" in log_calls[0][0]


def test_retry_with_log_no_log_fn():
    """Test retry_with_log without log function (should work)."""
    clock = FakeClock()
    call = FailNTimes(fail_count=1)
    
    result = retry_with_log(
        call,
        attempts=3,
        base_ms=100,
        jitter_off=True,
        deterministic_clock=clock,
        log_fn=None,
    )
    
    assert result == "success"


def test_retry_timeout_with_log():
    """Test timeout with retry_with_log."""
    clock = FakeClock()
    
    def slow_fail():
        clock.advance(0.5)
        raise ValueError("Failed")
    
    log_calls = []
    
    def log_fn(message: str, attempt: int, exception: Exception):
        log_calls.append((message, attempt))
    
    with pytest.raises(TimeoutError):
        retry_with_log(
            slow_fail,
            attempts=10,
            base_ms=100,
            jitter_off=True,
            deterministic_clock=clock,
            timeout_ms=1000,
            log_fn=log_fn,
        )
    
    # Should have logged at least one failure before timeout
    assert len(log_calls) >= 1


def test_retry_backoff_capped_by_timeout():
    """Test that backoff delay is capped by remaining timeout."""
    clock = FakeClock()
    
    attempts_made = []
    
    def track_attempts():
        attempts_made.append(clock.current_time)
        raise ValueError("Failed")
    
    with pytest.raises(TimeoutError):
        retry(
            track_attempts,
            attempts=10,
            base_ms=500,  # Would normally wait 500ms, 1000ms, 2000ms...
            jitter_off=True,
            deterministic_clock=clock,
            timeout_ms=800,  # Timeout after 800ms
        )
    
    # Should have made at least 2 attempts before timeout
    assert len(attempts_made) >= 2


def test_retry_single_attempt():
    """Test retry with attempts=1 (no retry)."""
    call = FailNTimes(fail_count=1)
    
    with pytest.raises(ValueError, match="Attempt 1 failed"):
        retry(call, attempts=1, base_ms=100, jitter_off=True)
    
    assert call.attempts == 1


def test_retry_deterministic_across_runs():
    """Test that retry behavior is deterministic across runs."""
    clock1 = FakeClock()
    call1 = FailNTimes(fail_count=2)
    
    result1 = retry(
        call1,
        attempts=5,
        base_ms=100,
        jitter_off=False,
        idem_key="same_key",
        deterministic_clock=clock1,
    )
    
    # Second run with same conditions
    clock2 = FakeClock()
    call2 = FailNTimes(fail_count=2)
    
    result2 = retry(
        call2,
        attempts=5,
        base_ms=100,
        jitter_off=False,
        idem_key="same_key",
        deterministic_clock=clock2,
    )
    
    # Results should be identical
    assert result1 == result2
    assert call1.attempts == call2.attempts


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


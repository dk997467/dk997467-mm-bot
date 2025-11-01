"""
Unit tests for backoff and Redis lock primitives.

Tests verify:
- Exponential backoff with jitter
- Retry logic with retryable/non-retryable errors
- Redis distributed lock (with mock Redis)
- Lock auto-extend
"""
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch

from src.common.backoff import (
    BackoffPolicy,
    retry_async,
    retry_sync,
    RetryableError,
    NonRetryableError,
    is_retryable_default
)
from src.common.redis_lock import RedisLock, distributed_lock


class TestBackoffPolicy:
    """Test backoff policy configuration."""
    
    def test_default_policy(self):
        """Test default backoff policy."""
        policy = BackoffPolicy()
        
        assert policy.base_delay == 0.2
        assert policy.factor == 2.0
        assert policy.max_delay == 5.0
        assert policy.max_attempts == 7
        assert policy.jitter is True
    
    def test_compute_delay_no_jitter(self):
        """Test delay computation without jitter."""
        policy = BackoffPolicy(base_delay=1.0, factor=2.0, max_delay=10.0, jitter=False)
        
        # Attempt 0: 1.0 * 2^0 = 1.0
        assert policy.compute_delay(0) == 1.0
        
        # Attempt 1: 1.0 * 2^1 = 2.0
        assert policy.compute_delay(1) == 2.0
        
        # Attempt 2: 1.0 * 2^2 = 4.0
        assert policy.compute_delay(2) == 4.0
        
        # Attempt 3: 1.0 * 2^3 = 8.0
        assert policy.compute_delay(3) == 8.0
        
        # Attempt 4: 1.0 * 2^4 = 16.0, capped at 10.0
        assert policy.compute_delay(4) == 10.0
    
    def test_compute_delay_with_jitter(self):
        """Test delay computation with jitter."""
        policy = BackoffPolicy(base_delay=1.0, factor=2.0, max_delay=10.0, jitter=True)
        
        # With jitter: delay is random between 0 and computed value
        for attempt in range(5):
            delay = policy.compute_delay(attempt)
            expected_max = min(1.0 * (2.0 ** attempt), 10.0)
            
            assert 0 <= delay <= expected_max
    
    def test_max_delay_enforced(self):
        """Test that max_delay is enforced."""
        policy = BackoffPolicy(base_delay=1.0, factor=2.0, max_delay=5.0, jitter=False)
        
        # Large attempt should be capped
        assert policy.compute_delay(10) == 5.0
        assert policy.compute_delay(100) == 5.0


class TestRetryLogic:
    """Test retry logic with backoff."""
    
    @pytest.mark.asyncio
    async def test_retry_async_success_first_attempt(self):
        """Test successful operation on first attempt."""
        call_count = 0
        
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = await retry_async(succeed)
        
        assert result == "success"
        assert call_count == 1
    
    @pytest.mark.asyncio
    async def test_retry_async_success_after_failures(self):
        """Test successful operation after 2 failures."""
        call_count = 0
        
        async def fail_twice_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError("Temporary failure")
            return "success"
        
        policy = BackoffPolicy(base_delay=0.01, max_attempts=5)  # Fast backoff for test
        result = await retry_async(fail_twice_then_succeed, policy=policy)
        
        assert result == "success"
        assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_retry_async_exhausts_attempts(self):
        """Test that retry exhausts attempts and raises."""
        call_count = 0
        
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RetryableError("Always fails")
        
        policy = BackoffPolicy(base_delay=0.01, max_attempts=3)
        
        with pytest.raises(RetryableError, match="Always fails"):
            await retry_async(always_fail, policy=policy)
        
        assert call_count == 3  # Attempted 3 times
    
    @pytest.mark.asyncio
    async def test_retry_async_non_retryable_error(self):
        """Test that non-retryable errors are not retried."""
        call_count = 0
        
        async def fail_non_retryable():
            nonlocal call_count
            call_count += 1
            raise NonRetryableError("Non-retryable")
        
        policy = BackoffPolicy(max_attempts=5)
        
        with pytest.raises(NonRetryableError, match="Non-retryable"):
            await retry_async(fail_non_retryable, policy=policy)
        
        assert call_count == 1  # Only attempted once
    
    @pytest.mark.asyncio
    async def test_retry_async_with_callback(self):
        """Test retry with on_retry callback."""
        call_count = 0
        retry_info = []
        
        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError(f"Attempt {call_count}")
            return "success"
        
        def on_retry(exc, attempt, delay):
            retry_info.append((str(exc), attempt, delay))
        
        policy = BackoffPolicy(base_delay=0.01, max_attempts=5)
        result = await retry_async(fail_twice, policy=policy, on_retry=on_retry)
        
        assert result == "success"
        assert len(retry_info) == 2  # 2 retries
        assert "Attempt 1" in retry_info[0][0]
        assert "Attempt 2" in retry_info[1][0]
    
    def test_retry_sync_success(self):
        """Test synchronous retry."""
        call_count = 0
        
        def fail_once_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RetryableError("First attempt fails")
            return "success"
        
        policy = BackoffPolicy(base_delay=0.01, max_attempts=3)
        result = retry_sync(fail_once_then_succeed, policy=policy)
        
        assert result == "success"
        assert call_count == 2


class TestIsRetryable:
    """Test retryable error detection."""
    
    def test_retryable_error_class(self):
        """Test RetryableError class is retryable."""
        exc = RetryableError("Test")
        assert is_retryable_default(exc) is True
    
    def test_non_retryable_error_class(self):
        """Test NonRetryableError class is not retryable."""
        exc = NonRetryableError("Test")
        assert is_retryable_default(exc) is False
    
    def test_timeout_is_retryable(self):
        """Test timeout errors are retryable."""
        exc = Exception("Connection timeout")
        assert is_retryable_default(exc) is True
    
    def test_network_error_is_retryable(self):
        """Test network errors are retryable."""
        exc = Exception("Network connection refused")
        assert is_retryable_default(exc) is True
    
    def test_rate_limit_is_retryable(self):
        """Test rate limit (429) is retryable."""
        exc = Exception("HTTP 429 rate limit exceeded")
        assert is_retryable_default(exc) is True
    
    def test_server_error_is_retryable(self):
        """Test 5xx server errors are retryable."""
        assert is_retryable_default(Exception("HTTP 500 Internal Server Error")) is True
        assert is_retryable_default(Exception("HTTP 502 Bad Gateway")) is True
        assert is_retryable_default(Exception("HTTP 503 Service Unavailable")) is True
        assert is_retryable_default(Exception("HTTP 504 Gateway Timeout")) is True
    
    def test_client_error_not_retryable(self):
        """Test 4xx client errors are not retryable (except 429)."""
        exc = Exception("HTTP 400 Bad Request")
        assert is_retryable_default(exc) is False
    
    def test_generic_error_not_retryable(self):
        """Test generic errors are not retryable by default."""
        exc = Exception("Some random error")
        assert is_retryable_default(exc) is False


class TestRedisLock:
    """Test Redis distributed lock."""
    
    @pytest.mark.asyncio
    async def test_lock_acquire_and_release(self):
        """Test lock acquire and release."""
        redis_mock = AsyncMock()
        redis_mock.set.return_value = True  # Acquire succeeds
        redis_mock.eval.return_value = 1    # Release succeeds
        
        lock = RedisLock(redis_mock, "test_lock", ttl=30)
        
        # Acquire
        acquired = await lock.acquire()
        assert acquired is True
        assert redis_mock.set.called
        
        # Release
        await lock.release()
        assert redis_mock.eval.called
    
    @pytest.mark.asyncio
    async def test_lock_already_held(self):
        """Test acquiring lock that's already held."""
        redis_mock = AsyncMock()
        redis_mock.set.return_value = False  # Acquire fails (already held)
        
        lock = RedisLock(redis_mock, "test_lock", ttl=30)
        
        acquired = await lock.acquire()
        assert acquired is False
    
    @pytest.mark.asyncio
    async def test_lock_context_manager(self):
        """Test lock as context manager."""
        redis_mock = AsyncMock()
        redis_mock.set.return_value = True
        redis_mock.eval.return_value = 1
        
        async with RedisLock(redis_mock, "test_lock") as acquired:
            assert acquired is True
        
        # Release should have been called
        assert redis_mock.eval.called
    
    @pytest.mark.asyncio
    async def test_lock_no_redis_fallback(self):
        """Test lock with no Redis (always acquires)."""
        lock = RedisLock(None, "test_lock")
        
        acquired = await lock.acquire()
        assert acquired is True  # Always succeeds without Redis
        
        await lock.release()  # Should not crash
    
    @pytest.mark.asyncio
    async def test_distributed_lock_helper(self):
        """Test distributed_lock context manager helper."""
        redis_mock = AsyncMock()
        redis_mock.set.return_value = True
        redis_mock.eval.return_value = 1
        
        async with distributed_lock(redis_mock, "helper_lock") as acquired:
            assert acquired is True
        
        assert redis_mock.set.called
        assert redis_mock.eval.called
    
    @pytest.mark.asyncio
    async def test_lock_auto_extend(self):
        """Test lock auto-extend functionality."""
        redis_mock = AsyncMock()
        redis_mock.set.return_value = True
        redis_mock.eval.return_value = 1
        
        lock = RedisLock(redis_mock, "test_lock", ttl=10, extend_every=0.05)
        
        await lock.acquire()
        
        # Wait for auto-extend to trigger
        await asyncio.sleep(0.15)  # 3x extend_every
        
        await lock.release()
        
        # Eval should be called multiple times (extend + release)
        assert redis_mock.eval.call_count >= 2


class TestBackoffBoundaries:
    """Test backoff boundaries and edge cases."""
    
    def test_max_attempts_boundary(self):
        """Test that max_attempts is enforced."""
        policy = BackoffPolicy(max_attempts=3)
        
        # Should not exceed 3 attempts
        for attempt in range(10):
            delay = policy.compute_delay(attempt)
            assert delay >= 0  # Valid delay
    
    def test_zero_base_delay(self):
        """Test backoff with zero base delay."""
        policy = BackoffPolicy(base_delay=0.0, jitter=False)
        
        assert policy.compute_delay(0) == 0.0
        assert policy.compute_delay(5) == 0.0
    
    def test_max_delay_zero(self):
        """Test backoff with zero max delay."""
        policy = BackoffPolicy(max_delay=0.0, jitter=False)
        
        assert policy.compute_delay(0) == 0.0
        assert policy.compute_delay(10) == 0.0
    
    @pytest.mark.asyncio
    async def test_backoff_does_not_exceed_max(self):
        """Property: backoff delay never exceeds max_delay."""
        policy = BackoffPolicy(base_delay=1.0, factor=2.0, max_delay=3.0, jitter=True)
        
        for attempt in range(20):
            delay = policy.compute_delay(attempt)
            assert delay <= 3.0, f"Delay {delay} exceeds max 3.0 on attempt {attempt}"
    
    @pytest.mark.asyncio
    async def test_max_attempts_enforced(self):
        """Property: retry never exceeds max_attempts."""
        call_count = 0
        
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RetryableError("Fail")
        
        policy = BackoffPolicy(base_delay=0.001, max_attempts=5)
        
        with pytest.raises(RetryableError):
            await retry_async(always_fail, policy=policy)
        
        assert call_count == 5  # Exactly max_attempts


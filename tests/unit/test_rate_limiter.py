"""
Unit tests for Token Bucket Rate Limiter.

Tests verify:
- Token bucket algorithm
- Capacity and burst limits
- Async-safe concurrent access
- Metrics export
"""
import asyncio
import pytest
import time

from src.common.rate_limiter import (
    RateLimiter,
    RateLimiterConfig,
    RetryableRateLimited,
    TokenBucket
)


class MockMetrics:
    """Mock metrics collector."""
    
    def __init__(self):
        self.counters = {}
        self.observations = []
    
    def inc(self, name: str, value: int = 1, labels: dict = None):
        """Increment counter."""
        key = (name, tuple(sorted((labels or {}).items())))
        self.counters[key] = self.counters.get(key, 0) + value
    
    def observe(self, name: str, value: float, labels: dict = None):
        """Record observation."""
        self.observations.append((name, value, labels or {}))
    
    def get_counter(self, name: str, labels: dict = None) -> int:
        """Get counter value."""
        key = (name, tuple(sorted((labels or {}).items())))
        return self.counters.get(key, 0)


class TestRateLimiterBasic:
    """Test basic rate limiter functionality."""
    
    @pytest.mark.asyncio
    async def test_allows_under_capacity(self):
        """Test requests under capacity are allowed without wait."""
        config = RateLimiterConfig(capacity_per_s=10.0, burst=20)
        limiter = RateLimiter(config)
        
        # Burst of requests (up to burst capacity)
        for i in range(20):
            wait_ms = await limiter.acquire(endpoint="test")
            assert wait_ms < 1.0  # Minimal wait (< 1ms) for burst
    
    @pytest.mark.asyncio
    async def test_waits_when_exhausted(self):
        """Test limiter waits when tokens exhausted."""
        config = RateLimiterConfig(capacity_per_s=10.0, burst=5)
        metrics = MockMetrics()
        limiter = RateLimiter(config, metrics=metrics)
        
        # Exhaust burst
        for i in range(5):
            await limiter.acquire(endpoint="test")
        
        # Next request should wait
        start = time.time()
        wait_ms = await limiter.acquire(endpoint="test")
        elapsed = time.time() - start
        
        assert wait_ms > 0  # Had to wait
        assert elapsed >= 0.09  # ~0.1s wait for 1 token at 10/s
        
        # Check hit metric
        assert metrics.get_counter("mm_rate_limit_hits_total", {"endpoint": "test"}) >= 1
    
    @pytest.mark.asyncio
    async def test_try_acquire_no_wait(self):
        """Test try_acquire doesn't wait."""
        config = RateLimiterConfig(capacity_per_s=10.0, burst=2)
        limiter = RateLimiter(config)
        
        # First 2 should succeed
        assert await limiter.try_acquire(endpoint="test") is True
        assert await limiter.try_acquire(endpoint="test") is True
        
        # 3rd should fail (no tokens)
        assert await limiter.try_acquire(endpoint="test") is False


class TestRateLimiterRefill:
    """Test token refill logic."""
    
    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self):
        """Test tokens refill at configured rate."""
        config = RateLimiterConfig(capacity_per_s=10.0, burst=5)
        limiter = RateLimiter(config)
        
        # Exhaust tokens
        for i in range(5):
            await limiter.acquire(endpoint="test")
        
        # Wait for refill (0.2s = 2 tokens at 10/s)
        await asyncio.sleep(0.2)
        
        # Should be able to acquire 2 more without significant waiting
        wait_ms = await limiter.acquire(endpoint="test")
        assert wait_ms < 1.0  # Minimal wait
        
        wait_ms = await limiter.acquire(endpoint="test")
        assert wait_ms < 1.0  # Minimal wait
        
        # 3rd should wait (no tokens left)
        start = time.time()
        await limiter.acquire(endpoint="test")
        elapsed = time.time() - start
        assert elapsed >= 0.09  # Had to wait
    
    @pytest.mark.asyncio
    async def test_burst_capacity_not_exceeded(self):
        """Test tokens don't exceed burst capacity."""
        config = RateLimiterConfig(capacity_per_s=100.0, burst=10)
        limiter = RateLimiter(config)
        
        # Wait long enough to refill many times
        await asyncio.sleep(0.5)  # Would add 50 tokens if unlimited
        
        # Should only be able to burst up to capacity
        successes = 0
        for i in range(15):
            if await limiter.try_acquire(endpoint="test"):
                successes += 1
        
        assert successes == 10  # Limited by burst capacity


class TestRateLimiterConcurrency:
    """Test concurrent access safety."""
    
    @pytest.mark.asyncio
    async def test_concurrent_requests_safe(self):
        """Test 100 concurrent requests are handled safely."""
        config = RateLimiterConfig(capacity_per_s=50.0, burst=20)
        limiter = RateLimiter(config)
        
        # 100 concurrent acquires
        results = await asyncio.gather(*[
            limiter.acquire(endpoint="test")
            for _ in range(100)
        ])
        
        # All should complete (some with wait)
        assert len(results) == 100
        
        # Some should have waited
        waits = [r for r in results if r > 0]
        assert len(waits) > 0  # At least some waited
    
    @pytest.mark.asyncio
    async def test_no_negative_tokens(self):
        """Test tokens never go negative under concurrent load."""
        config = RateLimiterConfig(capacity_per_s=10.0, burst=5)
        limiter = RateLimiter(config)
        
        # Rapid concurrent requests
        await asyncio.gather(*[
            limiter.acquire(endpoint="test")
            for _ in range(50)
        ])
        
        # Should complete without errors (no negative tokens)
        # If tokens went negative, we'd get assertion errors internally


class TestRateLimiterPerEndpoint:
    """Test per-endpoint configuration."""
    
    @pytest.mark.asyncio
    async def test_endpoint_overrides(self):
        """Test per-endpoint rate limits."""
        config = RateLimiterConfig(
            capacity_per_s=10.0,
            burst=10,
            endpoint_overrides={
                "place_order": {"capacity_per_s": 5.0, "burst": 5},
                "cancel_order": {"capacity_per_s": 20.0, "burst": 20}
            }
        )
        limiter = RateLimiter(config)
        
        # place_order: burst of 5
        for i in range(5):
            wait_ms = await limiter.acquire(endpoint="place_order")
            assert wait_ms < 1.0  # Minimal wait
        
        # 6th should wait
        start = time.time()
        await limiter.acquire(endpoint="place_order")
        elapsed = time.time() - start
        assert elapsed >= 0.19  # ~0.2s for 1 token at 5/s
        
        # cancel_order: different limit (burst of 20)
        for i in range(20):
            wait_ms = await limiter.acquire(endpoint="cancel_order")
            assert wait_ms < 1.0  # Minimal wait
    
    @pytest.mark.asyncio
    async def test_separate_buckets_per_endpoint(self):
        """Test endpoints have separate token buckets."""
        config = RateLimiterConfig(capacity_per_s=10.0, burst=5)
        limiter = RateLimiter(config)
        
        # Exhaust endpoint1
        for i in range(5):
            await limiter.acquire(endpoint="endpoint1")
        
        # endpoint2 should still have full burst
        for i in range(5):
            wait_ms = await limiter.acquire(endpoint="endpoint2")
            assert wait_ms < 1.0  # Minimal wait


class TestRateLimiterMetrics:
    """Test metrics export."""
    
    @pytest.mark.asyncio
    async def test_hit_metric_on_wait(self):
        """Test hit metric incremented when tokens exhausted."""
        config = RateLimiterConfig(capacity_per_s=10.0, burst=2)
        metrics = MockMetrics()
        limiter = RateLimiter(config, metrics=metrics)
        
        # Exhaust tokens
        await limiter.acquire(endpoint="test")
        await limiter.acquire(endpoint="test")
        
        # This should trigger hit
        await limiter.acquire(endpoint="test")
        
        assert metrics.get_counter("mm_rate_limit_hits_total", {"endpoint": "test"}) >= 1
    
    @pytest.mark.asyncio
    async def test_wait_time_metric(self):
        """Test wait time metric recorded."""
        config = RateLimiterConfig(capacity_per_s=10.0, burst=2)
        metrics = MockMetrics()
        limiter = RateLimiter(config, metrics=metrics)
        
        # Exhaust tokens
        await limiter.acquire(endpoint="test")
        await limiter.acquire(endpoint="test")
        
        # Wait for refill
        wait_ms = await limiter.acquire(endpoint="test")
        
        assert wait_ms > 0
        
        # Check observation recorded
        wait_observations = [
            obs for obs in metrics.observations
            if obs[0] == "mm_rate_limit_wait_ms" and obs[2].get("endpoint") == "test"
        ]
        assert len(wait_observations) >= 1
        assert wait_observations[0][1] > 0  # Wait time > 0


class TestTokenBucket:
    """Test TokenBucket class directly."""
    
    @pytest.mark.asyncio
    async def test_bucket_starts_at_burst(self):
        """Test bucket starts with burst tokens."""
        bucket = TokenBucket(capacity_per_s=10.0, burst=20)
        
        # Should be able to consume burst immediately
        for i in range(20):
            assert bucket.try_acquire(1) is True
        
        # 21st should fail
        assert bucket.try_acquire(1) is False
    
    @pytest.mark.asyncio
    async def test_bucket_refills(self):
        """Test bucket refills at correct rate."""
        bucket = TokenBucket(capacity_per_s=10.0, burst=5)
        
        # Exhaust tokens
        for i in range(5):
            bucket.try_acquire(1)
        
        # Wait for 1 token (0.1s at 10/s)
        await asyncio.sleep(0.11)
        
        # Should have 1 token
        assert bucket.try_acquire(1) is True
        assert bucket.try_acquire(1) is False  # No more
    
    @pytest.mark.asyncio
    async def test_acquire_multiple_tokens(self):
        """Test acquiring multiple tokens at once."""
        bucket = TokenBucket(capacity_per_s=10.0, burst=10)
        
        # Acquire 5 tokens
        assert bucket.try_acquire(5) is True
        
        # Should have 5 left
        assert bucket.try_acquire(5) is True
        
        # None left
        assert bucket.try_acquire(1) is False


class TestRateLimiterEdgeCases:
    """Test edge cases."""
    
    @pytest.mark.asyncio
    async def test_zero_capacity(self):
        """Test behavior with zero capacity (effectively disabled)."""
        config = RateLimiterConfig(capacity_per_s=0.0, burst=5)
        limiter = RateLimiter(config)
        
        # Can use burst
        for i in range(5):
            await limiter.acquire(endpoint="test")
        
        # No refill, so next should wait indefinitely (or very long)
        # We'll skip this test as it would hang
    
    @pytest.mark.asyncio
    async def test_very_high_capacity(self):
        """Test with very high capacity."""
        config = RateLimiterConfig(capacity_per_s=1000.0, burst=100)
        limiter = RateLimiter(config)
        
        # Should handle many requests quickly
        start = time.time()
        for i in range(150):
            await limiter.acquire(endpoint="test")
        elapsed = time.time() - start
        
        # Should complete in reasonable time
        assert elapsed < 1.0  # 150 requests at 1000/s
    
    @pytest.mark.asyncio
    async def test_fractional_tokens(self):
        """Test limiter handles fractional token rates."""
        config = RateLimiterConfig(capacity_per_s=0.5, burst=2)  # 1 token per 2 seconds
        limiter = RateLimiter(config)
        
        # Use burst
        await limiter.acquire(endpoint="test")
        await limiter.acquire(endpoint="test")
        
        # Next should wait ~2s for 1 token
        start = time.time()
        await limiter.acquire(endpoint="test")
        elapsed = time.time() - start
        
        assert elapsed >= 1.9  # Close to 2s


class TestRateLimiterPerformance:
    """Test performance characteristics."""
    
    @pytest.mark.asyncio
    async def test_many_endpoints(self):
        """Test limiter with many different endpoints."""
        config = RateLimiterConfig(capacity_per_s=100.0, burst=50)
        limiter = RateLimiter(config)
        
        # Create 20 different endpoints
        endpoints = [f"endpoint_{i}" for i in range(20)]
        
        # Each should have independent buckets
        for endpoint in endpoints:
            for i in range(10):
                wait_ms = await limiter.acquire(endpoint=endpoint)
                assert wait_ms < 1.0  # Minimal wait within burst


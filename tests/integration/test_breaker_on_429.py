"""
Integration test for Circuit Breaker + Rate Limiter on exchange errors.

Tests verify:
- Circuit breaker opens on repeated 429/5xx errors
- Allowlist endpoints bypass breaker
- Rate limiter protects against burst traffic
- Combined breaker + limiter behavior
"""
import asyncio
import pytest
from dataclasses import dataclass
from typing import Optional

from src.common.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    RetryableCircuitOpenError
)
from src.common.rate_limiter import (
    RateLimiter,
    RateLimiterConfig,
    RetryableRateLimited
)


@dataclass
class MockMetrics:
    """Mock metrics collector."""
    
    def __init__(self):
        self.counters = {}
        self.gauges = {}
        self.observations = []
    
    def inc(self, name: str, value: int = 1, labels: dict = None):
        """Increment counter."""
        key = (name, tuple(sorted((labels or {}).items())))
        self.counters[key] = self.counters.get(key, 0) + value
    
    def set(self, name: str, value: float, labels: dict = None):
        """Set gauge."""
        key = (name, tuple(sorted((labels or {}).items())))
        self.gauges[key] = value
    
    def observe(self, name: str, value: float, labels: dict = None):
        """Record observation."""
        self.observations.append((name, value, labels or {}))


class MockExchange:
    """Mock exchange that can simulate errors."""
    
    def __init__(self):
        self.call_count = 0
        self.error_sequence = []  # List of (call_num, error_msg) tuples
        self.placed_orders = []
        self.canceled_orders = []
    
    def set_error_sequence(self, sequence):
        """Set sequence of errors to return."""
        self.error_sequence = sequence
    
    async def place_order(self, symbol: str, side: str, qty: float, price: float):
        """Place order (may fail based on error sequence)."""
        self.call_count += 1
        
        # Check if we should raise an error
        for call_num, error_msg in self.error_sequence:
            if self.call_count == call_num:
                raise Exception(error_msg)
        
        # Success
        order_id = f"order_{self.call_count}"
        self.placed_orders.append(order_id)
        return {"orderId": order_id, "status": "NEW"}
    
    async def cancel_order(self, order_id: str):
        """Cancel order."""
        self.canceled_orders.append(order_id)
        return {"orderId": order_id, "status": "CANCELED"}
    
    async def get_health(self):
        """Health check (allowlist)."""
        return {"status": "ok"}


class GuardedExchange:
    """Exchange wrapper with circuit breaker and rate limiter."""
    
    def __init__(
        self,
        exchange: MockExchange,
        breaker: CircuitBreaker,
        limiter: RateLimiter
    ):
        self.exchange = exchange
        self.breaker = breaker
        self.limiter = limiter
    
    async def place_order(self, symbol: str, side: str, qty: float, price: float):
        """Guarded place_order with breaker + limiter."""
        # Rate limiter first
        await self.limiter.acquire(endpoint="place_order")
        
        # Circuit breaker check
        if not await self.breaker.allow_request(is_allowlist=False):
            raise RetryableCircuitOpenError("Circuit breaker open")
        
        # Call exchange
        try:
            result = await self.exchange.place_order(symbol, side, qty, price)
            await self.breaker.record_success()
            return result
        except Exception as exc:
            # Record failure if it's a circuit failure
            from src.common.circuit_breaker import is_circuit_failure, extract_error_code
            if is_circuit_failure(exc):
                error_code = extract_error_code(exc)
                await self.breaker.record_failure(error_code)
            raise
    
    async def cancel_order(self, order_id: str):
        """Guarded cancel_order."""
        await self.limiter.acquire(endpoint="cancel_order")
        
        if not await self.breaker.allow_request(is_allowlist=False):
            raise RetryableCircuitOpenError("Circuit breaker open")
        
        return await self.exchange.cancel_order(order_id)
    
    async def get_health(self):
        """Health check - allowlist (bypasses breaker)."""
        await self.limiter.acquire(endpoint="health")
        
        # Always allowed (allowlist)
        if not await self.breaker.allow_request(is_allowlist=True):
            pass  # Doesn't matter, allowlist always proceeds
        
        return await self.exchange.get_health()


@pytest.mark.integration
class TestBreakerOn429:
    """Test circuit breaker behavior on 429 errors."""
    
    @pytest.mark.asyncio
    async def test_breaker_opens_on_repeated_429(self):
        """Test breaker opens after repeated 429 errors."""
        # Setup
        exchange = MockExchange()
        metrics = MockMetrics()
        
        breaker_config = CircuitBreakerConfig(
            window_s=60.0,
            fail_threshold=3,
            cooldown_s=0.2,
            min_dwell_s=0.1
        )
        breaker = CircuitBreaker(breaker_config, metrics=metrics, endpoint_name="place_order")
        
        limiter_config = RateLimiterConfig(capacity_per_s=100.0, burst=100)  # High limits
        limiter = RateLimiter(limiter_config, metrics=metrics)
        
        guarded = GuardedExchange(exchange, breaker, limiter)
        
        # Set exchange to return 429 errors
        exchange.set_error_sequence([
            (1, "HTTP 429 Rate Limit Exceeded"),
            (2, "HTTP 429 Rate Limit Exceeded"),
            (3, "HTTP 429 Rate Limit Exceeded")
        ])
        
        # Try to place 3 orders (all will fail with 429)
        for i in range(3):
            with pytest.raises(Exception, match="429"):
                await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        # Wait for breaker to open
        await asyncio.sleep(0.15)
        
        # Breaker should be OPEN
        assert breaker.state == CircuitState.OPEN
        
        # 4th attempt should be blocked by breaker
        with pytest.raises(RetryableCircuitOpenError):
            await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        # Check metrics
        assert metrics.counters[("mm_api_failures_total", (("code", "429"), ("endpoint", "place_order")))] == 3
    
    @pytest.mark.asyncio
    async def test_breaker_opens_on_5xx_errors(self):
        """Test breaker opens on repeated 5xx errors."""
        exchange = MockExchange()
        metrics = MockMetrics()
        
        breaker_config = CircuitBreakerConfig(
            fail_threshold=5,
            min_dwell_s=0.05
        )
        breaker = CircuitBreaker(breaker_config, metrics=metrics, endpoint_name="place_order")
        
        limiter = RateLimiter(metrics=metrics)
        guarded = GuardedExchange(exchange, breaker, limiter)
        
        # Simulate 5 consecutive 500 errors
        exchange.set_error_sequence([
            (i, "HTTP 500 Internal Server Error") for i in range(1, 6)
        ])
        
        for i in range(5):
            with pytest.raises(Exception, match="500"):
                await guarded.place_order("ETHUSDT", "SELL", 0.1, 3000.0)
        
        await asyncio.sleep(0.1)
        
        # Breaker should be open
        assert breaker.state == CircuitState.OPEN
        
        # Verify failure metrics
        assert metrics.counters[("mm_api_failures_total", (("code", "500"), ("endpoint", "place_order")))] == 5
    
    @pytest.mark.asyncio
    async def test_allowlist_bypasses_open_breaker(self):
        """Test allowlist endpoints work even when breaker is open."""
        exchange = MockExchange()
        metrics = MockMetrics()
        
        breaker_config = CircuitBreakerConfig(
            fail_threshold=2,
            min_dwell_s=0.05
        )
        breaker = CircuitBreaker(breaker_config, metrics=metrics, endpoint_name="place_order")
        
        limiter = RateLimiter(metrics=metrics)
        guarded = GuardedExchange(exchange, breaker, limiter)
        
        # Trip breaker with 2 failures
        exchange.set_error_sequence([
            (1, "HTTP 503 Service Unavailable"),
            (2, "HTTP 503 Service Unavailable")
        ])
        
        for i in range(2):
            with pytest.raises(Exception, match="503"):
                await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        await asyncio.sleep(0.1)
        assert breaker.state == CircuitState.OPEN
        
        # place_order should be blocked
        with pytest.raises(RetryableCircuitOpenError):
            await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        # But health check (allowlist) should work
        result = await guarded.get_health()
        assert result["status"] == "ok"
    
    @pytest.mark.asyncio
    async def test_breaker_half_open_probe_success(self):
        """Test breaker enters HALF_OPEN after cooldown and closes on success."""
        exchange = MockExchange()
        metrics = MockMetrics()
        
        breaker_config = CircuitBreakerConfig(
            fail_threshold=2,
            cooldown_s=0.2,
            min_dwell_s=0.1,
            probe_count=1
        )
        breaker = CircuitBreaker(breaker_config, metrics=metrics, endpoint_name="place_order")
        
        limiter = RateLimiter(metrics=metrics)
        guarded = GuardedExchange(exchange, breaker, limiter)
        
        # Trip breaker
        exchange.set_error_sequence([
            (1, "timeout"),
            (2, "timeout")
        ])
        
        for i in range(2):
            with pytest.raises(Exception, match="timeout"):
                await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        await asyncio.sleep(0.15)
        assert breaker.state == CircuitState.OPEN
        
        # Wait for cooldown
        await asyncio.sleep(0.15)  # Total 0.3s > cooldown
        
        # Check state (triggers update)
        await breaker.allow_request()
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Clear error sequence (next call succeeds)
        exchange.error_sequence = []
        
        # Successful probe
        result = await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        assert result["status"] == "NEW"
        
        await asyncio.sleep(0.15)
        
        # Breaker should be CLOSED
        assert breaker.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_breaker_half_open_probe_failure(self):
        """Test breaker reopens on probe failure in HALF_OPEN."""
        exchange = MockExchange()
        metrics = MockMetrics()
        
        breaker_config = CircuitBreakerConfig(
            fail_threshold=2,
            cooldown_s=0.15,
            min_dwell_s=0.05
        )
        breaker = CircuitBreaker(breaker_config, metrics=metrics, endpoint_name="place_order")
        
        limiter = RateLimiter(metrics=metrics)
        guarded = GuardedExchange(exchange, breaker, limiter)
        
        # Trip breaker
        exchange.set_error_sequence([
            (1, "HTTP 502 Bad Gateway"),
            (2, "HTTP 502 Bad Gateway")
        ])
        
        for i in range(2):
            with pytest.raises(Exception, match="502"):
                await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        await asyncio.sleep(0.1)
        assert breaker.state == CircuitState.OPEN
        
        # Wait for cooldown → HALF_OPEN
        await asyncio.sleep(0.15)
        await breaker.allow_request()
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Probe fails
        exchange.set_error_sequence([(3, "HTTP 502 Bad Gateway")])
        
        with pytest.raises(Exception, match="502"):
            await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        await asyncio.sleep(0.1)
        
        # Breaker should reopen
        assert breaker.state == CircuitState.OPEN


@pytest.mark.integration
class TestRateLimiterIntegration:
    """Test rate limiter integration."""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_throttles_requests(self):
        """Test rate limiter throttles requests at configured rate."""
        exchange = MockExchange()
        metrics = MockMetrics()
        
        breaker = CircuitBreaker(metrics=metrics, endpoint_name="place_order")
        
        limiter_config = RateLimiterConfig(capacity_per_s=5.0, burst=5)
        limiter = RateLimiter(limiter_config, metrics=metrics)
        
        guarded = GuardedExchange(exchange, breaker, limiter)
        
        # Burst of 10 orders
        start = asyncio.get_event_loop().time()
        
        for i in range(10):
            await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        elapsed = asyncio.get_event_loop().time() - start
        
        # Should take at least 1 second (5 burst + 5 more at 5/s = 1s)
        assert elapsed >= 0.9
        
        # Check hit metrics (should have hits after burst exhausted)
        assert metrics.counters.get(("mm_rate_limit_hits_total", (("endpoint", "place_order"),)), 0) >= 1
    
    @pytest.mark.asyncio
    async def test_combined_breaker_and_limiter(self):
        """Test circuit breaker and rate limiter work together."""
        exchange = MockExchange()
        metrics = MockMetrics()
        
        breaker_config = CircuitBreakerConfig(
            fail_threshold=3,
            min_dwell_s=0.05
        )
        breaker = CircuitBreaker(breaker_config, metrics=metrics, endpoint_name="place_order")
        
        limiter_config = RateLimiterConfig(capacity_per_s=20.0, burst=10)
        limiter = RateLimiter(limiter_config, metrics=metrics)
        
        guarded = GuardedExchange(exchange, breaker, limiter)
        
        # First 3 calls fail → trip breaker
        exchange.set_error_sequence([
            (1, "HTTP 429"),
            (2, "HTTP 429"),
            (3, "HTTP 429")
        ])
        
        for i in range(3):
            with pytest.raises(Exception):
                await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        await asyncio.sleep(0.1)
        assert breaker.state == CircuitState.OPEN
        
        # Further calls blocked by breaker (doesn't even hit rate limiter)
        with pytest.raises(RetryableCircuitOpenError):
            await guarded.place_order("BTCUSDT", "BUY", 0.01, 50000.0)
        
        # Verify both metrics present
        assert ("mm_api_failures_total", (("code", "429"), ("endpoint", "place_order"))) in metrics.counters
        assert metrics.gauges.get(("mm_circuit_state", (("endpoint", "place_order"),))) == CircuitState.OPEN


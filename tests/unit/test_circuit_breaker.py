"""
Unit tests for Circuit Breaker implementation.

Tests verify:
- State transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
- Failure threshold enforcement
- Anti-flapping with min_dwell_s
- Allowlist bypass
- Metrics export
"""
import asyncio
import pytest
from unittest.mock import Mock

from src.common.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    RetryableCircuitOpenError,
    is_circuit_failure,
    extract_error_code
)


class MockMetrics:
    """Mock metrics collector."""
    
    def __init__(self):
        self.counters = {}
        self.gauges = {}
    
    def inc(self, name: str, value: int = 1, labels: dict = None):
        """Increment counter."""
        key = (name, tuple(sorted((labels or {}).items())))
        self.counters[key] = self.counters.get(key, 0) + value
    
    def set(self, name: str, value: float, labels: dict = None):
        """Set gauge."""
        key = (name, tuple(sorted((labels or {}).items())))
        self.gauges[key] = value
    
    def get_counter(self, name: str, labels: dict = None) -> int:
        """Get counter value."""
        key = (name, tuple(sorted((labels or {}).items())))
        return self.counters.get(key, 0)
    
    def get_gauge(self, name: str, labels: dict = None) -> float:
        """Get gauge value."""
        key = (name, tuple(sorted((labels or {}).items())))
        return self.gauges.get(key, 0.0)


class TestCircuitBreakerStateTransitions:
    """Test circuit breaker state transitions."""
    
    @pytest.mark.asyncio
    async def test_starts_in_closed_state(self):
        """Test breaker starts in CLOSED state."""
        config = CircuitBreakerConfig()
        breaker = CircuitBreaker(config)
        
        assert breaker.state == CircuitState.CLOSED
        assert await breaker.allow_request() is True
    
    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        """Test breaker opens after fail_threshold failures."""
        config = CircuitBreakerConfig(
            window_s=60.0,
            fail_threshold=5,
            min_dwell_s=0.1  # Fast for testing
        )
        metrics = MockMetrics()
        breaker = CircuitBreaker(config, metrics=metrics, endpoint_name="test")
        
        # Record 4 failures (below threshold)
        for i in range(4):
            await breaker.record_failure("500")
        
        assert breaker.state == CircuitState.CLOSED
        assert await breaker.allow_request() is True
        
        # 5th failure → should open
        await breaker.record_failure("500")
        
        # Wait for min_dwell
        await asyncio.sleep(0.15)
        
        assert breaker.state == CircuitState.OPEN
        assert await breaker.allow_request() is False
        
        # Check metrics
        assert metrics.get_counter("mm_api_failures_total", {"endpoint": "test", "code": "500"}) == 5
        assert metrics.get_gauge("mm_circuit_state", {"endpoint": "test"}) == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_half_open_after_cooldown(self):
        """Test breaker enters HALF_OPEN after cooldown."""
        config = CircuitBreakerConfig(
            fail_threshold=3,
            cooldown_s=0.2,
            min_dwell_s=0.1
        )
        breaker = CircuitBreaker(config)
        
        # Trip breaker
        for i in range(3):
            await breaker.record_failure("429")
        
        await asyncio.sleep(0.15)  # Wait for min_dwell
        assert breaker.state == CircuitState.OPEN
        
        # Wait for cooldown
        await asyncio.sleep(0.15)  # Total 0.3s > cooldown
        
        # Update state (happens on allow_request)
        await breaker.allow_request()
        
        assert breaker.state == CircuitState.HALF_OPEN
    
    @pytest.mark.asyncio
    async def test_half_open_probe_success_closes(self):
        """Test successful probe in HALF_OPEN closes breaker."""
        config = CircuitBreakerConfig(
            fail_threshold=2,
            cooldown_s=0.1,
            min_dwell_s=0.05,
            probe_count=1
        )
        metrics = MockMetrics()
        breaker = CircuitBreaker(config, metrics=metrics, endpoint_name="test")
        
        # Trip breaker
        await breaker.record_failure("500")
        await breaker.record_failure("500")
        await asyncio.sleep(0.06)
        
        assert breaker.state == CircuitState.OPEN
        
        # Wait for cooldown
        await asyncio.sleep(0.06)
        await breaker.allow_request()  # Trigger HALF_OPEN
        
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Successful probe
        await breaker.record_success()
        await asyncio.sleep(0.06)  # Wait for min_dwell
        
        assert breaker.state == CircuitState.CLOSED
        assert await breaker.allow_request() is True
    
    @pytest.mark.asyncio
    async def test_half_open_probe_failure_reopens(self):
        """Test failed probe in HALF_OPEN reopens breaker."""
        config = CircuitBreakerConfig(
            fail_threshold=2,
            cooldown_s=0.1,
            min_dwell_s=0.05
        )
        breaker = CircuitBreaker(config)
        
        # Trip breaker
        await breaker.record_failure("timeout")
        await breaker.record_failure("timeout")
        await asyncio.sleep(0.06)
        
        # Wait for cooldown → HALF_OPEN
        await asyncio.sleep(0.06)
        await breaker.allow_request()
        
        assert breaker.state == CircuitState.HALF_OPEN
        
        # Failed probe
        await breaker.record_failure("503")
        await asyncio.sleep(0.06)
        
        assert breaker.state == CircuitState.OPEN
        assert await breaker.allow_request() is False


class TestCircuitBreakerAntiFlapping:
    """Test anti-flapping with min_dwell_s."""
    
    @pytest.mark.asyncio
    async def test_min_dwell_prevents_rapid_transitions(self):
        """Test min_dwell_s prevents rapid state changes."""
        config = CircuitBreakerConfig(
            fail_threshold=2,
            cooldown_s=0.3,  # Longer than min_dwell
            min_dwell_s=0.1  # Min dwell time
        )
        breaker = CircuitBreaker(config)
        
        # Trip breaker (CLOSED → OPEN is immediate/forced)
        await breaker.record_failure("500")
        await breaker.record_failure("500")
        
        assert breaker.state == CircuitState.OPEN
        
        # Try to transition before cooldown (should stay OPEN)
        await asyncio.sleep(0.05)  # Less than min_dwell
        await breaker.allow_request()
        
        # Should still be OPEN (cooldown not reached)
        assert breaker.state == CircuitState.OPEN
        
        # Wait past min_dwell but before cooldown
        await asyncio.sleep(0.10)  # Total 0.15s (< cooldown 0.3s)
        await breaker.allow_request()
        
        # Still OPEN (cooldown not reached yet)
        assert breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_failure_count_in_window(self):
        """Test that old failures outside window don't count."""
        config = CircuitBreakerConfig(
            window_s=0.2,  # Short window for testing
            fail_threshold=3,
            min_dwell_s=0.05
        )
        breaker = CircuitBreaker(config)
        
        # Record 2 failures
        await breaker.record_failure("500")
        await breaker.record_failure("500")
        
        # Wait for window to expire
        await asyncio.sleep(0.25)
        
        # Old failures should be expired
        assert breaker.get_failure_count() == 0
        
        # New failure shouldn't trip (only 1 in window)
        await breaker.record_failure("500")
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerAllowlist:
    """Test allowlist functionality."""
    
    @pytest.mark.asyncio
    async def test_allowlist_bypasses_open_circuit(self):
        """Test allowlist endpoints bypass OPEN circuit."""
        config = CircuitBreakerConfig(
            fail_threshold=2,
            min_dwell_s=0.05
        )
        breaker = CircuitBreaker(config)
        
        # Trip breaker
        await breaker.record_failure("500")
        await breaker.record_failure("500")
        await asyncio.sleep(0.06)
        
        assert breaker.state == CircuitState.OPEN
        
        # Regular request blocked
        assert await breaker.allow_request(is_allowlist=False) is False
        
        # Allowlist request allowed
        assert await breaker.allow_request(is_allowlist=True) is True


class TestCircuitBreakerMetrics:
    """Test metrics export."""
    
    @pytest.mark.asyncio
    async def test_metrics_exposed_on_failure(self):
        """Test failure metrics are incremented."""
        config = CircuitBreakerConfig(min_dwell_s=0.05)
        metrics = MockMetrics()
        breaker = CircuitBreaker(config, metrics=metrics, endpoint_name="place_order")
        
        # Record failures with different codes
        await breaker.record_failure("429")
        await breaker.record_failure("500")
        await breaker.record_failure("timeout")
        
        assert metrics.get_counter("mm_api_failures_total", {"endpoint": "place_order", "code": "429"}) == 1
        assert metrics.get_counter("mm_api_failures_total", {"endpoint": "place_order", "code": "500"}) == 1
        assert metrics.get_counter("mm_api_failures_total", {"endpoint": "place_order", "code": "timeout"}) == 1
    
    @pytest.mark.asyncio
    async def test_state_metric_changes(self):
        """Test circuit state metric changes."""
        config = CircuitBreakerConfig(
            fail_threshold=2,
            cooldown_s=0.1,
            min_dwell_s=0.05
        )
        metrics = MockMetrics()
        breaker = CircuitBreaker(config, metrics=metrics, endpoint_name="test")
        
        # Initial state
        assert breaker.state == CircuitState.CLOSED
        
        # Trip to OPEN
        await breaker.record_failure("500")
        await breaker.record_failure("500")
        await asyncio.sleep(0.06)
        
        assert metrics.get_gauge("mm_circuit_state", {"endpoint": "test"}) == CircuitState.OPEN
        
        # Wait for HALF_OPEN
        await asyncio.sleep(0.06)
        await breaker.allow_request()
        
        assert metrics.get_gauge("mm_circuit_state", {"endpoint": "test"}) == CircuitState.HALF_OPEN


class TestCircuitFailureDetection:
    """Test failure detection logic."""
    
    def test_is_circuit_failure_429(self):
        """Test 429 is detected as failure."""
        exc = Exception("HTTP 429 Rate Limit Exceeded")
        assert is_circuit_failure(exc) is True
    
    def test_is_circuit_failure_5xx(self):
        """Test 5xx errors are detected as failures."""
        assert is_circuit_failure(Exception("HTTP 500 Internal Server Error")) is True
        assert is_circuit_failure(Exception("HTTP 502 Bad Gateway")) is True
        assert is_circuit_failure(Exception("HTTP 503 Service Unavailable")) is True
        assert is_circuit_failure(Exception("HTTP 504 Gateway Timeout")) is True
    
    def test_is_circuit_failure_timeout(self):
        """Test timeout errors are detected as failures."""
        assert is_circuit_failure(Exception("Request timeout")) is True
        assert is_circuit_failure(Exception("Connection timed out")) is True
    
    def test_is_circuit_failure_network(self):
        """Test network errors are detected as failures."""
        assert is_circuit_failure(Exception("Connection refused")) is True
        assert is_circuit_failure(Exception("Connection reset by peer")) is True
        assert is_circuit_failure(Exception("Network error")) is True
    
    def test_is_not_circuit_failure_4xx(self):
        """Test 4xx (except 429) are not circuit failures."""
        assert is_circuit_failure(Exception("HTTP 400 Bad Request")) is False
        assert is_circuit_failure(Exception("HTTP 404 Not Found")) is False
    
    def test_extract_error_code(self):
        """Test error code extraction."""
        assert extract_error_code(Exception("HTTP 429")) == "429"
        assert extract_error_code(Exception("HTTP 500")) == "500"
        assert extract_error_code(Exception("timeout")) == "timeout"
        assert extract_error_code(Exception("connection refused")) == "refused"
        assert extract_error_code(Exception("random error")) == "unknown"


class TestCircuitBreakerEdgeCases:
    """Test edge cases."""
    
    @pytest.mark.asyncio
    async def test_multiple_probe_successes_required(self):
        """Test probe_count > 1 requires multiple successes."""
        config = CircuitBreakerConfig(
            fail_threshold=2,
            cooldown_s=0.1,
            min_dwell_s=0.05,
            probe_count=3  # Need 3 successes
        )
        breaker = CircuitBreaker(config)
        
        # Trip breaker
        await breaker.record_failure("500")
        await breaker.record_failure("500")
        await asyncio.sleep(0.06)
        
        # Enter HALF_OPEN
        await asyncio.sleep(0.06)
        await breaker.allow_request()
        
        assert breaker.state == CircuitState.HALF_OPEN
        
        # 2 successes (not enough)
        await breaker.record_success()
        await breaker.record_success()
        
        assert breaker.state == CircuitState.HALF_OPEN
        
        # 3rd success → close
        await breaker.record_success()
        await asyncio.sleep(0.06)
        
        assert breaker.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """Test circuit breaker is thread-safe."""
        config = CircuitBreakerConfig(fail_threshold=10, min_dwell_s=0.01)
        breaker = CircuitBreaker(config)
        
        # Concurrent checks
        results = await asyncio.gather(*[
            breaker.allow_request() for _ in range(100)
        ])
        
        # All should be allowed (CLOSED state)
        assert all(results)
        
        # Concurrent failures
        await asyncio.gather(*[
            breaker.record_failure("500") for _ in range(5)
        ])
        
        # Should have 5 failures
        assert breaker.get_failure_count() == 5


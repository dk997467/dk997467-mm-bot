"""
Circuit Breaker pattern implementation for API resilience.

Features:
- Sliding window failure tracking
- Three states: CLOSED, OPEN, HALF_OPEN
- Anti-flapping with minimum dwell time
- Allowlist for critical operations
- Async-safe with monotonic time
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Callable, Any
from collections import deque


class CircuitState(IntEnum):
    """Circuit breaker states."""
    CLOSED = 0      # Normal operation
    OPEN = 1        # Blocking calls (tripped)
    HALF_OPEN = 2   # Testing with probe calls


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    
    window_s: float = 60.0          # Sliding window duration
    fail_threshold: int = 10        # Failures to trip breaker
    cooldown_s: float = 30.0        # Time before HALF_OPEN
    min_dwell_s: float = 30.0       # Min time in state (anti-flapping)
    probe_count: int = 1            # Successful probes to close


class RetryableCircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """
    Circuit breaker with sliding window and state transitions.
    
    State machine:
        CLOSED --[>fail_threshold failures in window_s]--> OPEN
        OPEN --[after cooldown_s]--> HALF_OPEN
        HALF_OPEN --[probe_count successes]--> CLOSED
        HALF_OPEN --[any failure]--> OPEN
    
    Anti-flapping:
        State must dwell for min_dwell_s before transition allowed
    
    Usage:
        breaker = CircuitBreaker(config)
        
        # Check before call
        if not breaker.allow_request(endpoint="place_order"):
            raise RetryableCircuitOpenError("Circuit breaker open")
        
        try:
            result = await exchange.place_order(...)
            breaker.record_success()
        except Exception as exc:
            if is_failure(exc):
                breaker.record_failure()
            raise
    """
    
    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        metrics: Optional[Any] = None,
        endpoint_name: str = "default"
    ):
        """
        Initialize circuit breaker.
        
        Args:
            config: Circuit breaker configuration
            metrics: Metrics collector (optional)
            endpoint_name: Name of endpoint (for metrics)
        """
        self.config = config or CircuitBreakerConfig()
        self.metrics = metrics
        self.endpoint_name = endpoint_name
        
        # State
        self._state = CircuitState.CLOSED
        self._state_changed_at = time.monotonic()
        
        # Failure tracking (sliding window)
        self._failures: deque = deque()  # (timestamp, error_code)
        
        # HALF_OPEN probe tracking
        self._probe_successes = 0
        
        # Thread safety
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        """Get current state."""
        return self._state
    
    async def allow_request(self, is_allowlist: bool = False) -> bool:
        """
        Check if request is allowed.
        
        Args:
            is_allowlist: True for allowlist endpoints (always allowed)
        
        Returns:
            True if request allowed, False otherwise
        """
        async with self._lock:
            # Allowlist endpoints bypass circuit breaker
            if is_allowlist:
                return True
            
            # Update state based on conditions
            await self._update_state()
            
            # CLOSED: allow all requests
            if self._state == CircuitState.CLOSED:
                return True
            
            # OPEN: block all requests
            if self._state == CircuitState.OPEN:
                return False
            
            # HALF_OPEN: allow limited probes
            if self._state == CircuitState.HALF_OPEN:
                return True  # Caller must handle probe logic
            
            return False
    
    async def record_success(self):
        """Record successful request."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._probe_successes += 1
                
                # Enough successful probes → close circuit
                if self._probe_successes >= self.config.probe_count:
                    await self._transition_to(CircuitState.CLOSED, force=True)
    
    async def record_failure(self, error_code: str = "unknown"):
        """
        Record failed request.
        
        Args:
            error_code: Error code (e.g., "429", "500", "timeout")
        """
        async with self._lock:
            now = time.monotonic()
            
            # Add failure to sliding window
            self._failures.append((now, error_code))
            
            # Emit failure metric
            if self.metrics:
                self.metrics.inc(
                    "mm_api_failures_total",
                    labels={"endpoint": self.endpoint_name, "code": error_code}
                )
            
            # Clean old failures outside window
            cutoff = now - self.config.window_s
            while self._failures and self._failures[0][0] < cutoff:
                self._failures.popleft()
            
            # Check if we should open circuit
            if self._state == CircuitState.CLOSED:
                if len(self._failures) >= self.config.fail_threshold:
                    await self._transition_to(CircuitState.OPEN, force=True)
            
            # In HALF_OPEN: any failure → open again
            elif self._state == CircuitState.HALF_OPEN:
                await self._transition_to(CircuitState.OPEN, force=True)
    
    async def _update_state(self):
        """Update state based on conditions (cooldown, etc.)."""
        now = time.monotonic()
        time_in_state = now - self._state_changed_at
        
        # OPEN → HALF_OPEN after cooldown
        if self._state == CircuitState.OPEN:
            if time_in_state >= self.config.cooldown_s:
                # Check min_dwell before transition
                if time_in_state >= self.config.min_dwell_s:
                    await self._transition_to(CircuitState.HALF_OPEN)
    
    async def _transition_to(self, new_state: CircuitState, force: bool = False):
        """
        Transition to new state.
        
        Args:
            new_state: Target state
            force: If True, bypass min_dwell check (for safety-critical transitions)
        """
        now = time.monotonic()
        time_in_state = now - self._state_changed_at
        
        # Enforce minimum dwell time (anti-flapping)
        # Skip check if forced (safety-critical transitions)
        if not force:
            if time_in_state < self.config.min_dwell_s:
                return  # Too soon to transition
        
        old_state = self._state
        self._state = new_state
        self._state_changed_at = now
        
        # Reset probe counter on entering HALF_OPEN
        if new_state == CircuitState.HALF_OPEN:
            self._probe_successes = 0
        
        # Clear failures on entering CLOSED
        if new_state == CircuitState.CLOSED:
            self._failures.clear()
        
        # Emit state metric
        if self.metrics:
            self.metrics.set(
                "mm_circuit_state",
                int(new_state),
                labels={"endpoint": self.endpoint_name}
            )
        
        # Log transition
        # (optional: add structured logging here)
    
    def get_failure_count(self) -> int:
        """Get current failure count in window."""
        # Clean up old failures first
        now = time.monotonic()
        cutoff = now - self.config.window_s
        while self._failures and self._failures[0][0] < cutoff:
            self._failures.popleft()
        
        return len(self._failures)


def is_circuit_failure(exc: Exception) -> bool:
    """
    Determine if exception should count as circuit breaker failure.
    
    Failures:
    - HTTP 429 (rate limit)
    - HTTP 5xx (server errors)
    - Network/transport errors (timeout, connection, etc.)
    
    Args:
        exc: Exception to check
    
    Returns:
        True if should count as failure
    """
    exc_str = str(exc).lower()
    
    # HTTP 429 (rate limit)
    if '429' in exc_str or 'rate limit' in exc_str:
        return True
    
    # HTTP 5xx (server errors)
    if any(code in exc_str for code in ['500', '502', '503', '504']):
        return True
    
    # Network/transport errors
    if any(keyword in exc_str for keyword in [
        'timeout', 'timed out', 'connection', 'refused', 'reset', 'network'
    ]):
        return True
    
    return False


def extract_error_code(exc: Exception) -> str:
    """
    Extract error code from exception.
    
    Args:
        exc: Exception
    
    Returns:
        Error code string (e.g., "429", "500", "timeout")
    """
    exc_str = str(exc).lower()
    
    # Check for HTTP status codes
    for code in ['429', '500', '502', '503', '504']:
        if code in exc_str:
            return code
    
    # Check for network errors (order matters - check more specific first)
    if 'timeout' in exc_str or 'timed out' in exc_str:
        return 'timeout'
    
    if 'refused' in exc_str:
        return 'refused'
    
    if 'reset' in exc_str:
        return 'reset'
    
    if 'connection' in exc_str:
        return 'connection'
    
    return 'unknown'


"""
Token Bucket Rate Limiter for API rate limiting.

Features:
- Token bucket algorithm
- Async-safe with proper locking
- Configurable capacity and burst
- Per-endpoint overrides
- Metrics for hits and wait times
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class RateLimiterConfig:
    """Rate limiter configuration."""
    
    capacity_per_s: float = 8.0     # Tokens added per second
    burst: int = 16                  # Maximum token capacity (burst)
    endpoint_overrides: Dict[str, Dict[str, float]] = None  # Per-endpoint config
    
    def __post_init__(self):
        """Initialize endpoint overrides."""
        if self.endpoint_overrides is None:
            self.endpoint_overrides = {}


class RetryableRateLimited(Exception):
    """Raised when rate limit exceeded and no wait strategy."""
    pass


class RateLimiter:
    """
    Token bucket rate limiter with async support.
    
    Algorithm:
    - Tokens refill at rate: capacity_per_s tokens/second
    - Maximum tokens: burst
    - Each request consumes 1 token
    - If no tokens available: wait or raise exception
    
    Usage:
        limiter = RateLimiter(config)
        
        # Acquire token (wait if needed)
        await limiter.acquire(endpoint="place_order")
        
        # Or check without waiting
        if not limiter.try_acquire(endpoint="place_order"):
            raise RetryableRateLimited("Rate limit exceeded")
    """
    
    def __init__(
        self,
        config: Optional[RateLimiterConfig] = None,
        metrics: Optional[Any] = None
    ):
        """
        Initialize rate limiter.
        
        Args:
            config: Rate limiter configuration
            metrics: Metrics collector (optional)
        """
        self.config = config or RateLimiterConfig()
        self.metrics = metrics
        
        # Per-endpoint token buckets
        self._buckets: Dict[str, TokenBucket] = {}
        
        # Global lock for bucket access
        self._lock = asyncio.Lock()
    
    def _get_endpoint_config(self, endpoint: str) -> tuple[float, int]:
        """
        Get config for endpoint.
        
        Args:
            endpoint: Endpoint name
        
        Returns:
            (capacity_per_s, burst) tuple
        """
        if endpoint in self.config.endpoint_overrides:
            override = self.config.endpoint_overrides[endpoint]
            capacity = override.get('capacity_per_s', self.config.capacity_per_s)
            burst = int(override.get('burst', self.config.burst))
            return (capacity, burst)
        
        return (self.config.capacity_per_s, self.config.burst)
    
    def _get_or_create_bucket(self, endpoint: str) -> TokenBucket:
        """Get or create token bucket for endpoint."""
        if endpoint not in self._buckets:
            capacity, burst = self._get_endpoint_config(endpoint)
            self._buckets[endpoint] = TokenBucket(
                capacity_per_s=capacity,
                burst=burst,
                endpoint=endpoint,
                metrics=self.metrics
            )
        
        return self._buckets[endpoint]
    
    async def acquire(self, endpoint: str = "default", tokens: int = 1) -> float:
        """
        Acquire tokens (wait if needed).
        
        Args:
            endpoint: Endpoint name
            tokens: Number of tokens to acquire
        
        Returns:
            Wait time in milliseconds (0 if no wait)
        """
        async with self._lock:
            bucket = self._get_or_create_bucket(endpoint)
            wait_ms = await bucket.acquire(tokens)
            return wait_ms
    
    async def try_acquire(self, endpoint: str = "default", tokens: int = 1) -> bool:
        """
        Try to acquire tokens without waiting.
        
        Args:
            endpoint: Endpoint name
            tokens: Number of tokens to acquire
        
        Returns:
            True if acquired, False if insufficient tokens
        """
        async with self._lock:
            bucket = self._get_or_create_bucket(endpoint)
            return bucket.try_acquire(tokens)


class TokenBucket:
    """
    Token bucket for single endpoint.
    
    Thread-safe implementation with monotonic time.
    """
    
    def __init__(
        self,
        capacity_per_s: float,
        burst: int,
        endpoint: str = "default",
        metrics: Optional[Any] = None
    ):
        """
        Initialize token bucket.
        
        Args:
            capacity_per_s: Tokens added per second
            burst: Maximum token capacity
            endpoint: Endpoint name (for metrics)
            metrics: Metrics collector (optional)
        """
        self.capacity_per_s = capacity_per_s
        self.burst = burst
        self.endpoint = endpoint
        self.metrics = metrics
        
        # Current tokens (start at burst capacity)
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        
        # Condition for waiting
        self._condition = asyncio.Condition()
    
    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        
        # Add tokens based on elapsed time
        tokens_to_add = elapsed * self.capacity_per_s
        self._tokens = min(self._tokens + tokens_to_add, self.burst)
        self._last_refill = now
    
    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens (wait if needed).
        
        Args:
            tokens: Number of tokens to acquire
        
        Returns:
            Wait time in milliseconds
        """
        start_time = time.monotonic()
        wait_ms = 0.0
        
        async with self._condition:
            while True:
                self._refill()
                
                if self._tokens >= tokens:
                    # Enough tokens available
                    self._tokens -= tokens
                    break
                
                # Not enough tokens: wait for refill
                tokens_needed = tokens - self._tokens
                wait_time = tokens_needed / self.capacity_per_s
                
                # Emit hit metric (we had to wait)
                if self.metrics and wait_ms == 0.0:  # First wait
                    self.metrics.inc(
                        "mm_rate_limit_hits_total",
                        labels={"endpoint": self.endpoint}
                    )
                
                # Wait for refill
                try:
                    await asyncio.wait_for(
                        self._condition.wait(),
                        timeout=wait_time
                    )
                except asyncio.TimeoutError:
                    # Timeout is normal (wait for refill)
                    pass
                
                # Notify other waiters
                self._condition.notify_all()
        
        # Calculate total wait time
        end_time = time.monotonic()
        wait_ms = (end_time - start_time) * 1000
        
        # Emit wait metric
        if self.metrics and wait_ms > 0:
            self.metrics.observe(
                "mm_rate_limit_wait_ms",
                wait_ms,
                labels={"endpoint": self.endpoint}
            )
        
        return wait_ms
    
    def try_acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens without waiting.
        
        Args:
            tokens: Number of tokens to acquire
        
        Returns:
            True if acquired, False otherwise
        """
        self._refill()
        
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        
        # Not enough tokens: emit hit metric
        if self.metrics:
            self.metrics.inc(
                "mm_rate_limit_hits_total",
                labels={"endpoint": self.endpoint}
            )
        
        return False


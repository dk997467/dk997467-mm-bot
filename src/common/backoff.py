"""
Exponential backoff with jitter for retry logic.

Production-grade retry mechanism with:
- Exponential backoff
- Jitter to avoid thundering herd
- Configurable max attempts and max sleep
- Async support
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Callable, TypeVar, Any, Optional
from dataclasses import dataclass

T = TypeVar('T')


@dataclass
class BackoffPolicy:
    """Configuration for exponential backoff."""
    
    base_delay: float = 0.2  # Initial delay in seconds
    factor: float = 2.0      # Exponential factor
    max_delay: float = 5.0   # Maximum delay between retries
    max_attempts: int = 7    # Maximum number of attempts
    jitter: bool = True      # Add jitter to prevent thundering herd
    
    def compute_delay(self, attempt: int) -> float:
        """
        Compute delay for given attempt number.
        
        Args:
            attempt: Current attempt number (0-indexed)
        
        Returns:
            Delay in seconds
        """
        # Exponential: base * factor^attempt
        delay = self.base_delay * (self.factor ** attempt)
        
        # Cap at max_delay
        delay = min(delay, self.max_delay)
        
        # Add jitter: uniform random between 0 and delay
        if self.jitter:
            delay = random.uniform(0, delay)
        
        return delay


class RetryableError(Exception):
    """Base class for retryable errors."""
    pass


class NonRetryableError(Exception):
    """Base class for non-retryable errors."""
    pass


def is_retryable_default(exc: Exception) -> bool:
    """
    Default logic to determine if exception is retryable.
    
    Retryable: network errors, timeouts, 429, 5xx
    Non-retryable: 4xx (except 429), logic errors
    """
    if isinstance(exc, RetryableError):
        return True
    if isinstance(exc, NonRetryableError):
        return False
    
    exc_str = str(exc).lower()
    
    # Network/timeout errors (retryable)
    if any(keyword in exc_str for keyword in [
        'timeout', 'connection', 'network', 'refused', 'reset'
    ]):
        return True
    
    # HTTP status codes
    if '429' in exc_str or 'rate limit' in exc_str:
        return True  # Rate limit: retryable
    
    if any(code in exc_str for code in ['500', '502', '503', '504']):
        return True  # Server errors: retryable
    
    # Default: non-retryable
    return False


async def retry_async(
    fn: Callable[..., Any],
    *args,
    policy: Optional[BackoffPolicy] = None,
    is_retryable: Optional[Callable[[Exception], bool]] = None,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
    **kwargs
) -> T:
    """
    Retry async function with exponential backoff.
    
    Args:
        fn: Async function to retry
        *args: Positional arguments for fn
        policy: Backoff policy (default: BackoffPolicy())
        is_retryable: Function to check if exception is retryable
        on_retry: Callback called on each retry (exc, attempt, delay)
        **kwargs: Keyword arguments for fn
    
    Returns:
        Result of fn
    
    Raises:
        Last exception if all retries exhausted
    
    Example:
        >>> async def flaky_api_call():
        ...     if random.random() < 0.5:
        ...         raise RetryableError("Timeout")
        ...     return "success"
        >>> result = await retry_async(flaky_api_call)
    """
    policy = policy or BackoffPolicy()
    is_retryable_fn = is_retryable or is_retryable_default
    
    last_exception: Optional[Exception] = None
    
    for attempt in range(policy.max_attempts):
        try:
            result = await fn(*args, **kwargs)
            return result
        
        except Exception as exc:
            last_exception = exc
            
            # Check if retryable
            if not is_retryable_fn(exc):
                raise
            
            # Last attempt? Raise
            if attempt >= policy.max_attempts - 1:
                raise
            
            # Compute backoff delay
            delay = policy.compute_delay(attempt)
            
            # Callback
            if on_retry:
                on_retry(exc, attempt, delay)
            
            # Sleep with backoff
            await asyncio.sleep(delay)
    
    # Should never reach here, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("Retry logic error: no exception and no result")


def retry_sync(
    fn: Callable[..., Any],
    *args,
    policy: Optional[BackoffPolicy] = None,
    is_retryable: Optional[Callable[[Exception], bool]] = None,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
    **kwargs
) -> T:
    """
    Retry sync function with exponential backoff.
    
    Same as retry_async but for synchronous functions.
    """
    policy = policy or BackoffPolicy()
    is_retryable_fn = is_retryable or is_retryable_default
    
    last_exception: Optional[Exception] = None
    
    for attempt in range(policy.max_attempts):
        try:
            result = fn(*args, **kwargs)
            return result
        
        except Exception as exc:
            last_exception = exc
            
            if not is_retryable_fn(exc):
                raise
            
            if attempt >= policy.max_attempts - 1:
                raise
            
            delay = policy.compute_delay(attempt)
            
            if on_retry:
                on_retry(exc, attempt, delay)
            
            time.sleep(delay)
    
    if last_exception:
        raise last_exception
    raise RuntimeError("Retry logic error")


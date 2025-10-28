"""
Deterministic retry mechanism with exponential backoff.

Pure stdlib implementation with no random module for test stability.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Callable, TypeVar


T = TypeVar("T")


def _pseudo_jitter(idem_key: str, attempt: int) -> float:
    """
    Generate deterministic pseudo-jitter based on idempotency key.
    
    Args:
        idem_key: Idempotency key for stable jitter
        attempt: Attempt number
        
    Returns:
        Jitter factor between 0.0 and 1.0
    """
    # Create deterministic hash from idem_key and attempt
    data = f"{idem_key}:{attempt}".encode("utf-8")
    hash_digest = hashlib.sha256(data).hexdigest()
    
    # Convert first 8 hex chars to a number between 0 and 1
    hash_int = int(hash_digest[:8], 16)
    max_val = 16 ** 8
    jitter = hash_int / max_val
    
    return jitter


def retry(
    call: Callable[[], T],
    *,
    attempts: int = 3,
    base_ms: int = 100,
    jitter_off: bool = False,
    idem_key: str = "default",
    deterministic_clock: Callable[[], float] | None = None,
    timeout_ms: int | None = None,
) -> T:
    """
    Retry a callable with exponential backoff.
    
    Args:
        call: Callable to retry (should raise exception on failure)
        attempts: Maximum number of attempts (must be >= 1)
        base_ms: Base delay in milliseconds for backoff
        jitter_off: If True, disable jitter for perfectly deterministic timing
        idem_key: Idempotency key for deterministic jitter
        deterministic_clock: Optional injectable clock for testing
        timeout_ms: Optional timeout in milliseconds (cumulative across all attempts)
        
    Returns:
        Result from successful call
        
    Raises:
        Last exception if all attempts fail
        TimeoutError if timeout_ms is exceeded
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    
    clock = deterministic_clock or time.time
    start_time = clock()
    last_exception: Exception | None = None
    
    for attempt in range(1, attempts + 1):
        # Check timeout before attempting
        if timeout_ms is not None:
            elapsed_ms = (clock() - start_time) * 1000
            if elapsed_ms >= timeout_ms:
                raise TimeoutError(f"Retry timeout after {elapsed_ms:.0f}ms")
        
        try:
            result = call()
            return result
        except Exception as e:
            last_exception = e
            
            # If this was the last attempt, raise immediately
            if attempt >= attempts:
                break
            
            # Calculate backoff delay
            # Exponential: base * 2^(attempt-1)
            delay_ms = base_ms * (2 ** (attempt - 1))
            
            # Add jitter if enabled
            if not jitter_off:
                jitter = _pseudo_jitter(idem_key, attempt)
                # Jitter adds 0-50% of delay
                delay_ms += delay_ms * jitter * 0.5
            
            # Check if delay would exceed timeout
            if timeout_ms is not None:
                elapsed_ms = (clock() - start_time) * 1000
                remaining_ms = timeout_ms - elapsed_ms
                if remaining_ms <= 0:
                    raise TimeoutError(f"Retry timeout after {elapsed_ms:.0f}ms")
                delay_ms = min(delay_ms, remaining_ms)
            
            # Sleep for backoff duration
            delay_s = delay_ms / 1000.0
            if deterministic_clock is None:
                time.sleep(delay_s)
            else:
                # If deterministic_clock has an 'advance' method (like FakeClock),
                # advance it to simulate time passing
                if hasattr(deterministic_clock, 'advance'):
                    deterministic_clock.advance(delay_s)  # type: ignore[attr-defined]
    
    # All attempts failed, raise last exception
    if last_exception is not None:
        raise last_exception
    
    # Should never reach here, but satisfy type checker
    raise RuntimeError("Retry logic error: no exception but no result")


def retry_with_log(
    call: Callable[[], T],
    *,
    attempts: int = 3,
    base_ms: int = 100,
    jitter_off: bool = False,
    idem_key: str = "default",
    deterministic_clock: Callable[[], float] | None = None,
    timeout_ms: int | None = None,
    log_fn: Callable[[str, int, Exception], None] | None = None,
) -> T:
    """
    Retry with logging hook.
    
    Similar to retry() but calls log_fn on each failure before retrying.
    
    Args:
        call: Callable to retry
        attempts: Maximum number of attempts
        base_ms: Base delay in milliseconds
        jitter_off: If True, disable jitter
        idem_key: Idempotency key for deterministic jitter
        deterministic_clock: Optional injectable clock
        timeout_ms: Optional timeout in milliseconds
        log_fn: Optional logging function (message, attempt, exception)
        
    Returns:
        Result from successful call
        
    Raises:
        Last exception if all attempts fail
        TimeoutError if timeout_ms is exceeded
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    
    clock = deterministic_clock or time.time
    start_time = clock()
    last_exception: Exception | None = None
    
    for attempt in range(1, attempts + 1):
        if timeout_ms is not None:
            elapsed_ms = (clock() - start_time) * 1000
            if elapsed_ms >= timeout_ms:
                raise TimeoutError(f"Retry timeout after {elapsed_ms:.0f}ms")
        
        try:
            result = call()
            return result
        except Exception as e:
            last_exception = e
            
            if log_fn:
                log_fn(f"Attempt {attempt}/{attempts} failed", attempt, e)
            
            if attempt >= attempts:
                break
            
            delay_ms = base_ms * (2 ** (attempt - 1))
            
            if not jitter_off:
                jitter = _pseudo_jitter(idem_key, attempt)
                delay_ms += delay_ms * jitter * 0.5
            
            if timeout_ms is not None:
                elapsed_ms = (clock() - start_time) * 1000
                remaining_ms = timeout_ms - elapsed_ms
                if remaining_ms <= 0:
                    raise TimeoutError(f"Retry timeout after {elapsed_ms:.0f}ms")
                delay_ms = min(delay_ms, remaining_ms)
            
            delay_s = delay_ms / 1000.0
            if deterministic_clock is None:
                time.sleep(delay_s)
            else:
                # If deterministic_clock has an 'advance' method (like FakeClock),
                # advance it to simulate time passing
                if hasattr(deterministic_clock, 'advance'):
                    deterministic_clock.advance(delay_s)  # type: ignore[attr-defined]
    
    if last_exception is not None:
        raise last_exception
    
    raise RuntimeError("Retry logic error: no exception but no result")


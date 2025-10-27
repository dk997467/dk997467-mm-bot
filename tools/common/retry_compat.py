"""
Tenacity-compatible facade over stdlib-only retry.

Provides a tenacity-like API without external dependencies.
Maps to tools.common.retry internally.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional, Type, TypeVar, Any
import time

T = TypeVar("T")


class RetryError(Exception):
    """Raised when retry attempts are exhausted."""
    pass


@dataclass
class _StopAfterAttempt:
    """Stop condition: max attempts."""
    attempts: int


def stop_after_attempt(n: int) -> _StopAfterAttempt:
    """Create a stop condition for max N attempts."""
    return _StopAfterAttempt(attempts=n)


@dataclass
class _WaitExponential:
    """Wait strategy: exponential backoff."""
    multiplier: float = 1.0
    min: float = 0.0
    max: Optional[float] = None


def wait_exponential(
    multiplier: float = 1.0,
    min: float = 0.0,
    max: Optional[float] = None
) -> _WaitExponential:
    """Create exponential backoff wait strategy."""
    return _WaitExponential(multiplier=multiplier, min=min, max=max)


def retry_if_exception_type(exc_type: Type[BaseException]) -> Callable[[BaseException], bool]:
    """Create a predicate that retries only on specific exception types."""
    def _pred(exc: BaseException) -> bool:
        return isinstance(exc, exc_type)
    return _pred


def retry(
    stop: _StopAfterAttempt,
    wait: Optional[_WaitExponential] = None,
    retry: Optional[Callable[[BaseException], bool]] = None,
    reraise: bool = True,
):
    """
    Tenacity-like decorator facade (stdlib-only).
    
    Maps to exponential backoff with deterministic delays.
    Not 1:1 with tenacity, but preserves:
    - number of attempts
    - exponential backoff (approx)
    - conditional retry on exception type
    - reraise on exhaustion
    
    Args:
        stop: Stop condition (max attempts)
        wait: Wait strategy (exponential backoff)
        retry: Predicate to check if exception should be retried
        reraise: If True, reraise last exception; if False, raise RetryError
    """
    max_attempts = getattr(stop, "attempts", 3)

    # Map wait_exponential -> (base, cap)
    if wait is None:
        base_delay = 0.05
        cap_delay = 1.0
    else:
        base_delay = max(0.0, float(wait.multiplier))
        base_delay = base_delay if base_delay > 0 else 0.05
        cap_delay = float(wait.max) if wait.max is not None else 1.0
        cap_delay = max(cap_delay, base_delay)

    def _decorator(func: Callable[..., T]) -> Callable[..., T]:
        def _call(*args: Any, **kwargs: Any) -> T:
            attempts_left = max_attempts
            delay = base_delay
            last_exc: Optional[BaseException] = None
            
            while attempts_left > 0:
                try:
                    return func(*args, **kwargs)
                except BaseException as e:  # noqa: BLE001
                    # Should we retry this exception?
                    if retry is not None and not retry(e):
                        if reraise:
                            raise
                        # If not reraise, break and raise RetryError
                        last_exc = e
                        break

                    attempts_left -= 1
                    last_exc = e
                    
                    if attempts_left <= 0:
                        if reraise:
                            raise
                        raise RetryError(str(e)) from e
                    
                    # Sleep with exponential growth (bounded)
                    time.sleep(delay)
                    delay = min(delay * 2.0, cap_delay)
            
            # Exhausted without reraise
            if last_exc:
                raise RetryError(str(last_exc)) from last_exc
            raise RetryError("retry exhausted")
        
        return _call
    return _decorator


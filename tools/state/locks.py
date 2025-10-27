"""
Redlock-compatible distributed lock with in-memory fake for testing.

Provides concurrency control with precise TTL semantics.
Pure stdlib implementation.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Callable


class Redlock:
    """
    Redlock-compatible distributed lock.
    
    In-memory fake with precise TTL semantics and injectable deterministic clock.
    Suitable for testing race conditions and concurrency scenarios.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        """
        Initialize Redlock.
        
        Args:
            clock: Optional injectable clock for deterministic testing
        """
        self._clock = clock or time.time
        
        # resource -> (token, expiry_timestamp)
        self._locks: dict[str, tuple[str, float]] = {}

    def acquire(self, resource: str, ttl_ms: int) -> str | None:
        """
        Acquire lock for resource.
        
        Args:
            resource: Resource identifier
            ttl_ms: Time-to-live in milliseconds
            
        Returns:
            Lock token if acquired, None if already locked
        """
        now = self._clock()
        
        # Check if resource is already locked and not expired
        if resource in self._locks:
            token, expiry = self._locks[resource]
            if expiry > now:
                # Lock is still valid
                return None
            # Lock has expired, we can acquire it
        
        # Generate unique token
        token = secrets.token_hex(16)
        expiry = now + (ttl_ms / 1000.0)
        self._locks[resource] = (token, expiry)
        
        return token

    def release(self, resource: str, token: str) -> bool:
        """
        Release lock for resource.
        
        Args:
            resource: Resource identifier
            token: Lock token from acquire()
            
        Returns:
            True if lock was released, False if token didn't match or lock doesn't exist
        """
        now = self._clock()
        
        if resource not in self._locks:
            return False
        
        stored_token, expiry = self._locks[resource]
        
        # Check if lock has expired
        if expiry <= now:
            # Lock has expired, remove it
            del self._locks[resource]
            return False
        
        # Check if token matches
        if stored_token != token:
            return False
        
        # Release the lock
        del self._locks[resource]
        return True

    def refresh(self, resource: str, token: str, ttl_ms: int) -> bool:
        """
        Refresh lock TTL.
        
        Args:
            resource: Resource identifier
            token: Lock token from acquire()
            ttl_ms: New time-to-live in milliseconds
            
        Returns:
            True if lock was refreshed, False if token didn't match or lock expired
        """
        now = self._clock()
        
        if resource not in self._locks:
            return False
        
        stored_token, expiry = self._locks[resource]
        
        # Check if lock has expired
        if expiry <= now:
            # Lock has expired, remove it
            del self._locks[resource]
            return False
        
        # Check if token matches
        if stored_token != token:
            return False
        
        # Refresh the lock
        new_expiry = now + (ttl_ms / 1000.0)
        self._locks[resource] = (stored_token, new_expiry)
        return True

    def is_locked(self, resource: str) -> bool:
        """
        Check if resource is currently locked.
        
        Args:
            resource: Resource identifier
            
        Returns:
            True if resource is locked and not expired
        """
        now = self._clock()
        
        if resource not in self._locks:
            return False
        
        _, expiry = self._locks[resource]
        
        if expiry <= now:
            # Lock has expired
            del self._locks[resource]
            return False
        
        return True

    def get_ttl_ms(self, resource: str) -> int:
        """
        Get remaining TTL for lock in milliseconds.
        
        Args:
            resource: Resource identifier
            
        Returns:
            Remaining TTL in milliseconds, or -1 if lock doesn't exist or has expired
        """
        now = self._clock()
        
        if resource not in self._locks:
            return -1
        
        _, expiry = self._locks[resource]
        
        if expiry <= now:
            # Lock has expired
            del self._locks[resource]
            return -1
        
        remaining_ms = int((expiry - now) * 1000)
        return remaining_ms

    def clear_all(self) -> None:
        """Clear all locks (for testing)."""
        self._locks.clear()

    def get_all_locks(self) -> dict[str, tuple[str, float]]:
        """Get all current locks (for testing/debugging)."""
        now = self._clock()
        # Clean up expired locks
        expired = [r for r, (_, exp) in self._locks.items() if exp <= now]
        for r in expired:
            del self._locks[r]
        return self._locks.copy()


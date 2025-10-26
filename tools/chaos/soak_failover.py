#!/usr/bin/env python3
"""Fake KV lock for chaos/failover testing."""
from __future__ import annotations


class FakeKVLock:
    """
    Fake distributed lock for testing.
    
    Simulates lock acquire/release without actual backend.
    """
    
    def __init__(self, key: str):
        """
        Initialize fake lock.
        
        Args:
            key: Lock key name
        """
        self.key = key
        self._locked = False
    
    def acquire(self, timeout: float = 1.0) -> bool:
        """
        Acquire lock.
        
        Args:
            timeout: Timeout in seconds (ignored in fake)
        
        Returns:
            True if acquired, False otherwise
        """
        if not self._locked:
            self._locked = True
            return True
        return False
    
    def release(self) -> None:
        """Release lock."""
        self._locked = False
    
    def __enter__(self):
        """Context manager entry."""
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
        return False

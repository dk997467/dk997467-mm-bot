#!/usr/bin/env python3
"""Fake KV lock for chaos/failover testing."""
from __future__ import annotations


class FakeKVLock:
    """
    Fake distributed lock for testing with TTL and ownership tracking.
    
    Simulates lock acquire/release/renew with time-based expiry.
    """
    
    def __init__(self, key: str = "lock", ttl_ms: int = 1000):
        """
        Initialize fake lock.
        
        Args:
            key: Lock key name
            ttl_ms: Lock TTL in milliseconds
        """
        self.key = key
        self.ttl_ms = ttl_ms
        self.owner = None
        self._expiry_ts_ms = 0
        self.leader_elections_total = 0
        self.renew_fail_total = 0
    
    def try_acquire(self, owner: str, ts_ms: int) -> bool:
        """
        Try to acquire lock at given timestamp.
        
        Args:
            owner: Owner identifier
            ts_ms: Current timestamp in milliseconds
        
        Returns:
            True if acquired, False otherwise
        """
        # Lock is free if no owner or expired
        if self.owner is None or ts_ms >= self._expiry_ts_ms:
            self.owner = owner
            self._expiry_ts_ms = ts_ms + self.ttl_ms
            self.leader_elections_total += 1
            return True
        
        # Lock is held by someone else and not expired
        return False
    
    def renew(self, owner: str, ts_ms: int) -> bool:
        """
        Renew lock if owned by this owner and not expired.
        
        Args:
            owner: Owner identifier
            ts_ms: Current timestamp in milliseconds
        
        Returns:
            True if renewed, False otherwise
        """
        # Can only renew if you own it and it's not expired
        if self.owner == owner and ts_ms < self._expiry_ts_ms:
            self._expiry_ts_ms = ts_ms + self.ttl_ms
            return True
        
        # Renew failed
        self.renew_fail_total += 1
        return False
    
    # Legacy methods for backward compatibility
    def acquire(self, timeout: float = 1.0) -> bool:
        """
        Acquire lock (legacy API, no timestamp).
        
        Args:
            timeout: Timeout in seconds (ignored in fake)
        
        Returns:
            True if acquired, False otherwise
        """
        if self.owner is None:
            self.owner = "legacy"
            self._expiry_ts_ms = 999999999999  # Far future
            self.leader_elections_total += 1
            return True
        return False
    
    def release(self) -> None:
        """Release lock (legacy API)."""
        self.owner = None
        self._expiry_ts_ms = 0
    
    def __enter__(self):
        """Context manager entry."""
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
        return False


if __name__ == "__main__":
    import sys
    
    # Check for --smoke flag
    if "--smoke" in sys.argv:
        # Run smoke test
        lock = FakeKVLock(ttl_ms=1000)
        
        # Test acquire/renew/release cycle
        acquired = lock.try_acquire("worker1", 0)
        renewed = lock.renew("worker1", 500)
        lock.release()
        
        # Output log to stdout (must end with \n)
        log_msg = f"smoke_test: acquire={acquired} renew={renewed} elections={lock.leader_elections_total}\n"
        sys.stdout.write(log_msg)
        sys.exit(0)
    
    # Default behavior: print usage
    print("Usage: python -m tools.chaos.soak_failover --smoke")
    sys.exit(1)

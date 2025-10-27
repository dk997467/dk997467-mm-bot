"""
Redis-compatible key-value store with in-memory fake for testing.

Provides a unified interface for state storage with deterministic behavior.
Pure stdlib implementation.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable


class RedisKV:
    """
    Redis-compatible key-value store.
    
    Modes:
    - no_network=True: In-memory fake with same semantics (for CI/testing)
    - no_network=False: Stub raising NotImplementedError (live will be enabled later)
    
    JSON serialization: sorted keys, compact format, trailing newline.
    """

    def __init__(self, no_network: bool = True, clock: Callable[[], float] | None = None) -> None:
        """
        Initialize RedisKV.
        
        Args:
            no_network: If True, use in-memory fake; if False, raise NotImplementedError
            clock: Optional injectable clock for deterministic testing
        """
        self.no_network = no_network
        self._clock = clock or time.time
        
        if not no_network:
            raise NotImplementedError("Live Redis integration not yet implemented")
        
        # In-memory storage
        self._kv: dict[str, Any] = {}  # key -> value
        self._expiry: dict[str, float] = {}  # key -> expiry timestamp
        self._hashes: dict[str, dict[str, Any]] = {}  # key -> {field -> value}
        self._lists: dict[str, list[Any]] = {}  # key -> list of values

    def _cleanup_expired(self) -> None:
        """Remove expired keys."""
        now = self._clock()
        expired = [k for k, exp_time in self._expiry.items() if exp_time <= now]
        for key in expired:
            self._kv.pop(key, None)
            self._expiry.pop(key, None)
            self._hashes.pop(key, None)
            self._lists.pop(key, None)

    def _serialize(self, value: Any) -> str:
        """Serialize value to JSON with deterministic formatting."""
        return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"

    def _deserialize(self, data: str) -> Any:
        """Deserialize JSON string to value."""
        return json.loads(data.rstrip("\n"))

    # String operations
    def get(self, key: str) -> str | None:
        """Get value for key."""
        self._cleanup_expired()
        value = self._kv.get(key)
        if value is None:
            return None
        return value

    def set(self, key: str, value: Any, ex: int | None = None) -> None:
        """
        Set key to value.
        
        Args:
            key: Key to set
            value: Value (will be JSON-serialized)
            ex: Optional expiry time in seconds
        """
        self._cleanup_expired()
        self._kv[key] = self._serialize(value)
        
        if ex is not None:
            self._expiry[key] = self._clock() + ex
        else:
            self._expiry.pop(key, None)

    def delete(self, key: str) -> bool:
        """Delete key. Returns True if key existed."""
        self._cleanup_expired()
        existed = key in self._kv
        self._kv.pop(key, None)
        self._expiry.pop(key, None)
        self._hashes.pop(key, None)
        self._lists.pop(key, None)
        return existed

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        self._cleanup_expired()
        return key in self._kv or key in self._hashes or key in self._lists

    # Hash operations
    def hget(self, key: str, field: str) -> str | None:
        """Get hash field value."""
        self._cleanup_expired()
        hash_data = self._hashes.get(key, {})
        value = hash_data.get(field)
        if value is None:
            return None
        return value

    def hset(self, key: str, field: str, value: Any) -> None:
        """Set hash field to value."""
        self._cleanup_expired()
        if key not in self._hashes:
            self._hashes[key] = {}
        self._hashes[key][field] = self._serialize(value)

    def hmget(self, key: str, fields: list[str]) -> list[str | None]:
        """Get multiple hash fields."""
        self._cleanup_expired()
        hash_data = self._hashes.get(key, {})
        return [hash_data.get(field) for field in fields]

    def hmset(self, key: str, mapping: dict[str, Any]) -> None:
        """Set multiple hash fields."""
        self._cleanup_expired()
        if key not in self._hashes:
            self._hashes[key] = {}
        for field, value in mapping.items():
            self._hashes[key][field] = self._serialize(value)

    def hgetall(self, key: str) -> dict[str, str]:
        """Get all hash fields and values."""
        self._cleanup_expired()
        return self._hashes.get(key, {}).copy()

    def hdel(self, key: str, field: str) -> bool:
        """Delete hash field. Returns True if field existed."""
        self._cleanup_expired()
        if key not in self._hashes:
            return False
        existed = field in self._hashes[key]
        self._hashes[key].pop(field, None)
        if not self._hashes[key]:
            del self._hashes[key]
        return existed

    # List operations
    def lpush(self, key: str, value: Any) -> int:
        """Push value to left of list. Returns new length."""
        self._cleanup_expired()
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(0, self._serialize(value))
        return len(self._lists[key])

    def rpush(self, key: str, value: Any) -> int:
        """Push value to right of list. Returns new length."""
        self._cleanup_expired()
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].append(self._serialize(value))
        return len(self._lists[key])

    def lpop(self, key: str) -> str | None:
        """Pop value from left of list."""
        self._cleanup_expired()
        if key not in self._lists or not self._lists[key]:
            return None
        value = self._lists[key].pop(0)
        if not self._lists[key]:
            del self._lists[key]
        return value

    def rpop(self, key: str) -> str | None:
        """Pop value from right of list."""
        self._cleanup_expired()
        if key not in self._lists or not self._lists[key]:
            return None
        value = self._lists[key].pop()
        if not self._lists[key]:
            del self._lists[key]
        return value

    def llen(self, key: str) -> int:
        """Get list length."""
        self._cleanup_expired()
        return len(self._lists.get(key, []))

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        """Get list range."""
        self._cleanup_expired()
        if key not in self._lists:
            return []
        return self._lists[key][start:stop + 1]

    # Set operations
    def sadd(self, key: str, *values: Any) -> int:
        """Add values to set. Returns number of added elements."""
        self._cleanup_expired()
        if key not in self._kv:
            self._kv[key] = self._serialize(set())
        
        current_set = set(self._deserialize(self._kv[key]))
        initial_len = len(current_set)
        for value in values:
            current_set.add(self._serialize(value).rstrip("\n"))
        self._kv[key] = self._serialize(list(current_set))
        return len(current_set) - initial_len

    def smembers(self, key: str) -> set[str]:
        """Get all set members."""
        self._cleanup_expired()
        if key not in self._kv:
            return set()
        data = self._deserialize(self._kv[key])
        if isinstance(data, list):
            return set(data)
        return set()

    def srem(self, key: str, value: Any) -> bool:
        """Remove value from set. Returns True if value existed."""
        self._cleanup_expired()
        if key not in self._kv:
            return False
        
        current_set = set(self._deserialize(self._kv[key]))
        value_str = self._serialize(value).rstrip("\n")
        existed = value_str in current_set
        current_set.discard(value_str)
        self._kv[key] = self._serialize(list(current_set))
        return existed

    # Scan operation
    def scan(self, cursor: int = 0, match: str | None = None, count: int = 10) -> tuple[int, list[str]]:
        """
        Scan keys.
        
        Args:
            cursor: Starting cursor (0 to start)
            match: Optional pattern (simple prefix/suffix matching with *)
            count: Approximate number of keys to return
            
        Returns:
            (next_cursor, keys) - cursor is 0 when iteration is complete
        """
        self._cleanup_expired()
        
        all_keys = sorted(list(self._kv.keys()) + list(self._hashes.keys()) + list(self._lists.keys()))
        
        # Apply pattern matching
        if match:
            filtered = []
            for key in all_keys:
                if match.startswith("*") and match.endswith("*"):
                    # *pattern* - contains
                    pattern = match[1:-1]
                    if pattern in key:
                        filtered.append(key)
                elif match.startswith("*"):
                    # *pattern - ends with
                    pattern = match[1:]
                    if key.endswith(pattern):
                        filtered.append(key)
                elif match.endswith("*"):
                    # pattern* - starts with
                    pattern = match[:-1]
                    if key.startswith(pattern):
                        filtered.append(key)
                else:
                    # exact match
                    if key == match:
                        filtered.append(key)
            all_keys = filtered
        
        # Pagination
        start = cursor
        end = min(cursor + count, len(all_keys))
        result_keys = all_keys[start:end]
        next_cursor = end if end < len(all_keys) else 0
        
        return (next_cursor, result_keys)

    # Utility
    def flushall(self) -> None:
        """Clear all data (for testing)."""
        self._kv.clear()
        self._expiry.clear()
        self._hashes.clear()
        self._lists.clear()

    def keys(self, pattern: str = "*") -> list[str]:
        """Get all keys matching pattern."""
        _, result = self.scan(match=pattern, count=10000)
        return result

    def ttl(self, key: str) -> int:
        """Get TTL for key in seconds. Returns -1 if no expiry, -2 if key doesn't exist."""
        self._cleanup_expired()
        if not self.exists(key):
            return -2
        if key not in self._expiry:
            return -1
        ttl_seconds = int(self._expiry[key] - self._clock())
        return max(ttl_seconds, 0)


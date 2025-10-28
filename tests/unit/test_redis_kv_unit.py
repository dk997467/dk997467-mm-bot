"""
Unit tests for RedisKV in-memory implementation.

Tests:
- String operations (get/set/delete/exists)
- Hash operations (hget/hset/hmget/hmset/hgetall/hdel)
- List operations (lpush/rpush/lpop/rpop/llen/lrange)
- Set operations (sadd/smembers/srem)
- Scan operations with pattern matching
- TTL and expiry
- JSON serialization determinism
"""

from __future__ import annotations

import json
import time

import pytest

from tools.state.redis_client import RedisKV


class FakeClock:
    """Fake clock for deterministic testing."""
    
    def __init__(self, start_time: float = 1000.0):
        self.current_time = start_time
    
    def __call__(self) -> float:
        return self.current_time
    
    def advance(self, seconds: float) -> None:
        """Advance clock by seconds."""
        self.current_time += seconds


def test_redis_kv_basic_get_set():
    """Test basic get/set operations."""
    redis = RedisKV(no_network=True)
    
    # Set and get string
    redis.set("key1", "value1")
    assert redis.get("key1") == json.dumps("value1", sort_keys=True, separators=(",", ":")) + "\n"
    
    # Set and get dict
    redis.set("key2", {"a": 1, "b": 2})
    data = redis.get("key2")
    assert data == '{"a":1,"b":2}\n'  # Deterministic JSON
    
    # Non-existent key
    assert redis.get("nonexistent") is None


def test_redis_kv_delete_exists():
    """Test delete and exists operations."""
    redis = RedisKV(no_network=True)
    
    redis.set("key1", "value1")
    assert redis.exists("key1")
    
    # Delete existing key
    assert redis.delete("key1") is True
    assert not redis.exists("key1")
    
    # Delete non-existent key
    assert redis.delete("nonexistent") is False


def test_redis_kv_expiry():
    """Test expiry with TTL."""
    clock = FakeClock(start_time=0.0)
    redis = RedisKV(no_network=True, clock=clock)
    
    # Set with 10 second expiry
    redis.set("key1", "value1", ex=10)
    assert redis.get("key1") is not None
    assert redis.ttl("key1") == 10
    
    # Advance clock by 5 seconds
    clock.advance(5)
    assert redis.get("key1") is not None
    assert redis.ttl("key1") == 5
    
    # Advance clock past expiry
    clock.advance(6)
    assert redis.get("key1") is None
    assert redis.ttl("key1") == -2  # Key doesn't exist


def test_redis_kv_hash_operations():
    """Test hash operations."""
    redis = RedisKV(no_network=True)
    
    # hset and hget
    redis.hset("hash1", "field1", "value1")
    redis.hset("hash1", "field2", {"a": 1})
    
    assert redis.hget("hash1", "field1") == '"value1"\n'
    assert redis.hget("hash1", "field2") == '{"a":1}\n'
    assert redis.hget("hash1", "nonexistent") is None
    
    # hmget
    values = redis.hmget("hash1", ["field1", "field2", "field3"])
    assert values[0] == '"value1"\n'
    assert values[1] == '{"a":1}\n'
    assert values[2] is None
    
    # hmset
    redis.hmset("hash2", {"f1": "v1", "f2": "v2"})
    assert redis.hget("hash2", "f1") == '"v1"\n'
    assert redis.hget("hash2", "f2") == '"v2"\n'
    
    # hgetall
    all_fields = redis.hgetall("hash1")
    assert len(all_fields) == 2
    assert all_fields["field1"] == '"value1"\n'
    
    # hdel
    assert redis.hdel("hash1", "field1") is True
    assert redis.hget("hash1", "field1") is None
    assert redis.hdel("hash1", "nonexistent") is False


def test_redis_kv_list_operations():
    """Test list operations."""
    redis = RedisKV(no_network=True)
    
    # lpush and rpush
    assert redis.lpush("list1", "a") == 1
    assert redis.lpush("list1", "b") == 2
    assert redis.rpush("list1", "c") == 3
    
    # llen
    assert redis.llen("list1") == 3
    
    # lrange
    items = redis.lrange("list1", 0, 2)
    assert items == ['"b"\n', '"a"\n', '"c"\n']
    
    # lpop and rpop
    assert redis.lpop("list1") == '"b"\n'
    assert redis.rpop("list1") == '"c"\n'
    assert redis.llen("list1") == 1
    
    # Pop from empty
    redis.lpop("list1")
    assert redis.lpop("list1") is None


def test_redis_kv_set_operations():
    """Test set operations."""
    redis = RedisKV(no_network=True)
    
    # sadd
    assert redis.sadd("set1", "a") == 1
    assert redis.sadd("set1", "b", "c") == 2
    assert redis.sadd("set1", "a") == 0  # Duplicate
    
    # smembers
    members = redis.smembers("set1")
    assert len(members) == 3
    assert 'a' in members
    assert 'b' in members
    assert 'c' in members
    
    # srem
    assert redis.srem("set1", "b") is True
    members = redis.smembers("set1")
    assert len(members) == 2
    assert redis.srem("set1", "nonexistent") is False


def test_redis_kv_scan_operations():
    """Test scan with pattern matching."""
    redis = RedisKV(no_network=True)
    
    # Add multiple keys
    redis.set("user:1", "alice")
    redis.set("user:2", "bob")
    redis.set("order:1", "item1")
    redis.set("order:2", "item2")
    
    # Scan all keys
    cursor, keys = redis.scan(cursor=0, count=100)
    assert cursor == 0  # Complete iteration
    assert len(keys) == 4
    
    # Scan with prefix match
    cursor, keys = redis.scan(cursor=0, match="user:*", count=100)
    assert len(keys) == 2
    assert "user:1" in keys
    assert "user:2" in keys
    
    # Scan with suffix match
    cursor, keys = redis.scan(cursor=0, match="*:1", count=100)
    assert len(keys) == 2
    assert "user:1" in keys
    assert "order:1" in keys
    
    # Scan with contains match
    cursor, keys = redis.scan(cursor=0, match="*ser*", count=100)
    assert len(keys) == 2
    
    # Pagination
    redis.set("key:3", "v3")
    redis.set("key:4", "v4")
    cursor, keys = redis.scan(cursor=0, match="*", count=2)
    assert len(keys) == 2
    assert cursor > 0  # More data available


def test_redis_kv_keys_helper():
    """Test keys() helper method."""
    redis = RedisKV(no_network=True)
    
    redis.set("user:1", "alice")
    redis.set("user:2", "bob")
    redis.set("order:1", "item1")
    
    # Get all keys
    all_keys = redis.keys("*")
    assert len(all_keys) == 3
    
    # Get filtered keys
    user_keys = redis.keys("user:*")
    assert len(user_keys) == 2


def test_redis_kv_flushall():
    """Test flushall operation."""
    redis = RedisKV(no_network=True)
    
    redis.set("key1", "value1")
    redis.hset("hash1", "field1", "value1")
    redis.lpush("list1", "item1")
    
    assert redis.exists("key1")
    assert redis.exists("hash1")
    assert redis.exists("list1")
    
    redis.flushall()
    
    assert not redis.exists("key1")
    assert not redis.exists("hash1")
    assert not redis.exists("list1")


def test_redis_kv_json_determinism():
    """Test JSON serialization is deterministic."""
    redis = RedisKV(no_network=True)
    
    # Set same dict multiple times
    data = {"z": 3, "a": 1, "m": 2}
    redis.set("key1", data)
    value1 = redis.get("key1")
    
    redis.set("key2", data)
    value2 = redis.get("key2")
    
    # Should be byte-identical (sorted keys)
    assert value1 == value2
    assert value1 == '{"a":1,"m":2,"z":3}\n'


def test_redis_kv_network_disabled():
    """Test that network mode raises NotImplementedError."""
    with pytest.raises(NotImplementedError, match="Live Redis integration not yet implemented"):
        RedisKV(no_network=False)


def test_redis_kv_ttl_no_expiry():
    """Test TTL on keys without expiry."""
    redis = RedisKV(no_network=True)
    
    redis.set("key1", "value1")
    assert redis.ttl("key1") == -1  # No expiry
    
    assert redis.ttl("nonexistent") == -2  # Key doesn't exist


def test_redis_kv_mixed_types():
    """Test that different data structures coexist."""
    redis = RedisKV(no_network=True)
    
    redis.set("string_key", "value")
    redis.hset("hash_key", "field", "value")
    redis.lpush("list_key", "item")
    
    # All should be accessible
    assert redis.exists("string_key")
    assert redis.exists("hash_key")
    assert redis.exists("list_key")
    
    # Scan should find all
    all_keys = redis.keys("*")
    assert len(all_keys) == 3


def test_redis_kv_delete_clears_all_types():
    """Test delete removes key from all storage types."""
    redis = RedisKV(no_network=True)
    
    redis.set("key1", "value", ex=60)
    redis.hset("key1", "field", "value")
    redis.lpush("key1", "item")
    
    # Delete should clear all
    redis.delete("key1")
    
    assert redis.get("key1") is None
    assert redis.hget("key1", "field") is None
    assert redis.llen("key1") == 0
    assert redis.ttl("key1") == -2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


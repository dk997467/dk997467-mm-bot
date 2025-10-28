#!/usr/bin/env python3
"""
Unit tests for tools/common/jsonx.py

Tests pure functions:
    - compute_json_hash
    - diff_json
"""

import pytest
from tools.common.jsonx import compute_json_hash, diff_json


# ======================================================================
# Test compute_json_hash
# ======================================================================


def test_compute_json_hash_simple_dict():
    """Test hash computation with simple dict."""
    obj = {"key": "value"}
    hash_val = compute_json_hash(obj)
    
    # Should return 64-char hex string (SHA256)
    assert isinstance(hash_val, str)
    assert len(hash_val) == 64
    assert all(c in "0123456789abcdef" for c in hash_val)


def test_compute_json_hash_deterministic():
    """Test that hash is deterministic (same input = same hash)."""
    obj = {"z": 1, "a": 2, "m": [3, 2, 1]}
    
    hash1 = compute_json_hash(obj)
    hash2 = compute_json_hash(obj)
    
    assert hash1 == hash2


def test_compute_json_hash_key_order_invariant():
    """Test that hash is independent of key order (sorted keys)."""
    obj1 = {"z": 1, "a": 2}
    obj2 = {"a": 2, "z": 1}
    
    hash1 = compute_json_hash(obj1)
    hash2 = compute_json_hash(obj2)
    
    # Should be identical (sorted keys)
    assert hash1 == hash2


def test_compute_json_hash_different_values():
    """Test that different values produce different hashes."""
    obj1 = {"key": "value1"}
    obj2 = {"key": "value2"}
    
    hash1 = compute_json_hash(obj1)
    hash2 = compute_json_hash(obj2)
    
    assert hash1 != hash2


def test_compute_json_hash_nested_dict():
    """Test hash with nested dict."""
    obj = {"outer": {"inner": 42, "list": [1, 2, 3]}}
    
    hash_val = compute_json_hash(obj)
    assert len(hash_val) == 64


def test_compute_json_hash_list():
    """Test hash with list."""
    obj = [1, 2, 3, {"a": 1}]
    
    hash_val = compute_json_hash(obj)
    assert len(hash_val) == 64


def test_compute_json_hash_empty_dict():
    """Test hash with empty dict."""
    hash_val = compute_json_hash({})
    assert len(hash_val) == 64


def test_compute_json_hash_numbers():
    """Test hash with different number types."""
    obj1 = {"value": 42}
    obj2 = {"value": 42.0}
    
    # JSON does distinguish int vs float in Python
    hash1 = compute_json_hash(obj1)
    hash2 = compute_json_hash(obj2)
    
    # Different types produce different hashes
    assert hash1 != hash2
    
    # But same type/value produces same hash
    assert compute_json_hash({"value": 42}) == compute_json_hash({"value": 42})
    assert compute_json_hash({"value": 42.0}) == compute_json_hash({"value": 42.0})


def test_compute_json_hash_nan_raises():
    """Test that NaN raises ValueError."""
    import math
    obj = {"value": math.nan}
    
    with pytest.raises(ValueError):
        compute_json_hash(obj)


def test_compute_json_hash_inf_raises():
    """Test that Infinity raises ValueError."""
    import math
    obj = {"value": math.inf}
    
    with pytest.raises(ValueError):
        compute_json_hash(obj)


# ======================================================================
# Test diff_json
# ======================================================================


def test_diff_json_no_changes():
    """Test diff with identical dicts."""
    old = {"a": 1, "b": 2}
    new = {"a": 1, "b": 2}
    
    diff = diff_json(old, new)
    
    assert diff["added"] == {}
    assert diff["removed"] == {}
    assert diff["changed"] == {}


def test_diff_json_added_keys():
    """Test diff with added keys."""
    old = {"a": 1}
    new = {"a": 1, "b": 2, "c": 3}
    
    diff = diff_json(old, new)
    
    assert diff["added"] == {"b": 2, "c": 3}
    assert diff["removed"] == {}
    assert diff["changed"] == {}


def test_diff_json_removed_keys():
    """Test diff with removed keys."""
    old = {"a": 1, "b": 2, "c": 3}
    new = {"a": 1}
    
    diff = diff_json(old, new)
    
    assert diff["added"] == {}
    assert diff["removed"] == {"b": 2, "c": 3}
    assert diff["changed"] == {}


def test_diff_json_changed_values():
    """Test diff with changed values."""
    old = {"a": 1, "b": 2}
    new = {"a": 1, "b": 3}
    
    diff = diff_json(old, new)
    
    assert diff["added"] == {}
    assert diff["removed"] == {}
    assert diff["changed"] == {"b": (2, 3)}


def test_diff_json_mixed_changes():
    """Test diff with added, removed, and changed keys."""
    old = {"a": 1, "b": 2, "c": 3}
    new = {"a": 1, "b": 99, "d": 4}
    
    diff = diff_json(old, new)
    
    assert diff["added"] == {"d": 4}
    assert diff["removed"] == {"c": 3}
    assert diff["changed"] == {"b": (2, 99)}


def test_diff_json_empty_old():
    """Test diff with empty old dict."""
    old = {}
    new = {"a": 1, "b": 2}
    
    diff = diff_json(old, new)
    
    assert diff["added"] == {"a": 1, "b": 2}
    assert diff["removed"] == {}
    assert diff["changed"] == {}


def test_diff_json_empty_new():
    """Test diff with empty new dict."""
    old = {"a": 1, "b": 2}
    new = {}
    
    diff = diff_json(old, new)
    
    assert diff["added"] == {}
    assert diff["removed"] == {"a": 1, "b": 2}
    assert diff["changed"] == {}


def test_diff_json_both_empty():
    """Test diff with both empty dicts."""
    diff = diff_json({}, {})
    
    assert diff["added"] == {}
    assert diff["removed"] == {}
    assert diff["changed"] == {}


def test_diff_json_non_dict_input():
    """Test diff with non-dict input (error case)."""
    old = [1, 2, 3]
    new = [1, 2, 4]
    
    diff = diff_json(old, new)
    
    # Should return error
    assert "error" in diff
    assert diff["error"] == "Only dict comparison supported"


def test_diff_json_value_type_change():
    """Test diff with value type change."""
    old = {"key": 123}
    new = {"key": "123"}
    
    diff = diff_json(old, new)
    
    assert diff["changed"] == {"key": (123, "123")}


def test_diff_json_nested_dict_change():
    """Test diff with nested dict (flat comparison only)."""
    old = {"config": {"param": 1}}
    new = {"config": {"param": 2}}
    
    diff = diff_json(old, new)
    
    # Should detect change (but not deep diff)
    assert diff["changed"] == {"config": ({"param": 1}, {"param": 2})}


# ======================================================================
# Run tests
# ======================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


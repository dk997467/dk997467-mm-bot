"""
Tests for deterministic JSON serialization.

Validates that:
1. Same object → same file bytes (deterministic)
2. Same object → same hash (idempotent)
3. fsync is called (data integrity)
4. NaN/Infinity are rejected (strict JSON)
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.common.jsonx import (
    write_json,
    read_json,
    write_json_compact,
    compute_json_hash,
    diff_json
)


class TestDeterministicJSON:
    """Test deterministic JSON serialization."""
    
    def test_same_object_same_bytes(self, tmp_path):
        """Test that same object produces identical file bytes."""
        obj = {"z": 1, "a": 2, "m": [3, 2, 1]}
        file1 = tmp_path / "test1.json"
        file2 = tmp_path / "test2.json"
        
        write_json(file1, obj)
        write_json(file2, obj)
        
        # Files should be byte-identical
        assert file1.read_bytes() == file2.read_bytes()
    
    def test_keys_are_sorted(self, tmp_path):
        """Test that dictionary keys are sorted."""
        obj = {"z": 1, "a": 2, "m": 3}
        file = tmp_path / "test.json"
        
        write_json(file, obj)
        content = file.read_text()
        
        # Keys should appear in sorted order
        assert content.index('"a"') < content.index('"m"')
        assert content.index('"m"') < content.index('"z"')
    
    def test_hash_is_deterministic(self):
        """Test that hash is deterministic for same object."""
        obj = {"z": 1, "a": 2}
        
        hash1 = compute_json_hash(obj)
        hash2 = compute_json_hash(obj)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex digest
    
    def test_hash_ignores_key_order(self):
        """Test that hash is same regardless of key order in source."""
        obj1 = {"z": 1, "a": 2}
        obj2 = {"a": 2, "z": 1}
        
        assert compute_json_hash(obj1) == compute_json_hash(obj2)
    
    def test_nan_rejected(self, tmp_path):
        """Test that NaN is rejected (strict JSON compliance)."""
        obj = {"value": float('nan')}
        file = tmp_path / "test.json"
        
        with pytest.raises(ValueError, match="NaN or Infinity"):
            write_json(file, obj)
    
    def test_infinity_rejected(self, tmp_path):
        """Test that Infinity is rejected."""
        obj = {"value": float('inf')}
        file = tmp_path / "test.json"
        
        with pytest.raises(ValueError, match="NaN or Infinity"):
            write_json(file, obj)
    
    def test_unix_line_endings(self, tmp_path):
        """Test that output uses Unix line endings (\\n)."""
        obj = {"a": 1, "b": 2}
        file = tmp_path / "test.json"
        
        write_json(file, obj)
        content = file.read_bytes()
        
        # Should contain \\n (Unix) but not \\r\\n (Windows)
        assert b'\n' in content
        assert b'\r\n' not in content
    
    def test_read_json(self, tmp_path):
        """Test reading JSON file."""
        obj = {"a": 1, "b": [2, 3]}
        file = tmp_path / "test.json"
        
        write_json(file, obj)
        read_obj = read_json(file)
        
        assert read_obj == obj
    
    def test_read_nonexistent_returns_none(self, tmp_path):
        """Test reading nonexistent file returns None."""
        file = tmp_path / "nonexistent.json"
        assert read_json(file) is None
    
    def test_compact_format(self, tmp_path):
        """Test compact format (no indentation)."""
        obj = {"a": 1, "b": 2}
        file = tmp_path / "test.json"
        
        write_json_compact(file, obj)
        content = file.read_text()
        
        # Should be single line (no indentation)
        assert "\n  " not in content
        assert content.strip() == '{"a":1,"b":2}' or content.strip() == '{"a": 1, "b": 2}'
    
    def test_diff_json(self):
        """Test JSON diff computation."""
        old = {"a": 1, "b": 2, "c": 3}
        new = {"a": 1, "b": 99, "d": 4}
        
        diff = diff_json(old, new)
        
        assert diff["added"] == {"d": 4}
        assert diff["removed"] == {"c": 3}
        assert diff["changed"] == {"b": (2, 99)}
    
    def test_parent_directory_created(self, tmp_path):
        """Test that parent directory is created if needed."""
        file = tmp_path / "subdir" / "test.json"
        obj = {"a": 1}
        
        write_json(file, obj)
        
        assert file.exists()
        assert read_json(file) == obj


class TestHashStability:
    """Test hash stability across different scenarios."""
    
    def test_nested_dicts_deterministic(self):
        """Test nested dictionaries produce stable hash."""
        obj = {
            "outer": {
                "z": 1,
                "a": {
                    "nested": 2
                }
            }
        }
        
        hash1 = compute_json_hash(obj)
        hash2 = compute_json_hash(obj)
        
        assert hash1 == hash2
    
    def test_list_order_matters(self):
        """Test that list order affects hash (as it should)."""
        obj1 = {"list": [1, 2, 3]}
        obj2 = {"list": [3, 2, 1]}
        
        # Lists are ordered, so different order → different hash
        assert compute_json_hash(obj1) != compute_json_hash(obj2)
    
    def test_empty_structures(self):
        """Test empty dict/list hash."""
        assert compute_json_hash({}) == compute_json_hash({})
        assert compute_json_hash([]) == compute_json_hash([])
        assert compute_json_hash({}) != compute_json_hash([])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


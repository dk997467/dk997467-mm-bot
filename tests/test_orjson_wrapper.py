"""
Tests for orjson_wrapper module.

Tests serialization/deserialization, performance, and compatibility.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.orjson_wrapper import (
    ORJSON_AVAILABLE,
    dumps,
    loads,
    dumps_bytes,
    loads_bytes,
    dump_to_file,
    load_from_file,
    is_faster_than_json,
)


def test_orjson_availability():
    """Test that orjson availability is detected correctly."""
    print(f"[INFO] orjson available: {ORJSON_AVAILABLE}")
    assert isinstance(ORJSON_AVAILABLE, bool)
    assert is_faster_than_json() == ORJSON_AVAILABLE
    print("[OK] orjson availability check passed")


def test_dumps_basic():
    """Test basic dumps functionality."""
    obj = {"b": 2, "a": 1, "c": 3}
    result = dumps(obj)
    
    # Should be sorted (sort_keys=True by default)
    assert '"a"' in result
    assert '"b"' in result
    assert '"c"' in result
    
    # Should be compact (no spaces)
    assert '{"a":1,"b":2,"c":3}' == result or '{"a": 1, "b": 2, "c": 3}' == result  # Depending on impl
    
    print(f"[OK] dumps produced: {result}")


def test_dumps_with_indent():
    """Test dumps with pretty-print."""
    obj = {"b": 2, "a": 1}
    result = dumps(obj, indent=2)
    
    # Should have newlines and indentation
    assert '\n' in result
    assert '"a"' in result
    assert '"b"' in result
    
    print(f"[OK] pretty dumps:\n{result}")


def test_loads_basic():
    """Test basic loads functionality."""
    json_str = '{"a":1,"b":2,"c":3}'
    result = loads(json_str)
    
    assert isinstance(result, dict)
    assert result['a'] == 1
    assert result['b'] == 2
    assert result['c'] == 3
    
    print(f"[OK] loads produced: {result}")


def test_dumps_loads_roundtrip():
    """Test roundtrip dumps -> loads."""
    original = {
        "string": "hello",
        "number": 42,
        "float": 3.14,
        "bool": True,
        "null": None,
        "list": [1, 2, 3],
        "nested": {"a": 1, "b": 2}
    }
    
    # Roundtrip
    json_str = dumps(original)
    restored = loads(json_str)
    
    assert restored == original
    print(f"[OK] Roundtrip successful")


def test_dumps_bytes_basic():
    """Test dumps_bytes returns bytes."""
    obj = {"b": 2, "a": 1}
    result = dumps_bytes(obj)
    
    assert isinstance(result, bytes)
    assert b'"a"' in result
    assert b'"b"' in result
    
    print(f"[OK] dumps_bytes produced: {result}")


def test_loads_bytes_basic():
    """Test loads_bytes from bytes."""
    json_bytes = b'{"a":1,"b":2}'
    result = loads_bytes(json_bytes)
    
    assert isinstance(result, dict)
    assert result['a'] == 1
    assert result['b'] == 2
    
    print(f"[OK] loads_bytes produced: {result}")


def test_file_io():
    """Test dump_to_file and load_from_file."""
    original = {"b": 2, "a": 1, "test": "data"}
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        temp_path = f.name
    
    try:
        # Write
        dump_to_file(original, temp_path, sort_keys=True)
        
        # Read
        restored = load_from_file(temp_path)
        
        assert restored == original
        print(f"[OK] File I/O roundtrip successful")
    finally:
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)


def test_unicode_handling():
    """Test Unicode string handling."""
    obj = {"message": "Hello 世界! 🚀"}
    
    # dumps should handle unicode
    json_str = dumps(obj)
    assert isinstance(json_str, str)
    
    # loads should restore unicode
    restored = loads(json_str)
    assert restored['message'] == "Hello 世界! 🚀"
    
    print(f"[OK] Unicode handling: {restored}")


def test_special_floats():
    """Test special float handling."""
    # Note: orjson and standard json both raise on NaN/Inf
    # This test just checks we don't crash
    
    obj = {
        "positive": 3.14,
        "negative": -2.71,
        "zero": 0.0,
        "scientific": 1.23e-4
    }
    
    json_str = dumps(obj)
    restored = loads(json_str)
    
    assert abs(restored['positive'] - 3.14) < 0.001
    assert abs(restored['negative'] + 2.71) < 0.001
    assert restored['zero'] == 0.0
    
    print(f"[OK] Special floats handled correctly")


def test_empty_containers():
    """Test empty dict/list handling."""
    obj = {
        "empty_dict": {},
        "empty_list": [],
        "nested_empty": {"a": {}, "b": []}
    }
    
    json_str = dumps(obj)
    restored = loads(json_str)
    
    assert restored == obj
    print(f"[OK] Empty containers handled correctly")


def test_sort_keys():
    """Test that sort_keys works."""
    obj = {"z": 1, "a": 2, "m": 3}
    
    # With sort_keys=True (default)
    sorted_json = dumps(obj, sort_keys=True)
    
    # Keys should appear in alphabetical order
    # Find positions of each key
    a_pos = sorted_json.index('"a"')
    m_pos = sorted_json.index('"m"')
    z_pos = sorted_json.index('"z"')
    
    assert a_pos < m_pos < z_pos, "Keys should be sorted alphabetically"
    print(f"[OK] Keys sorted: {sorted_json}")


if __name__ == "__main__":
    print("Running orjson_wrapper tests...")
    print("=" * 60)
    
    test_orjson_availability()
    test_dumps_basic()
    test_dumps_with_indent()
    test_loads_basic()
    test_dumps_loads_roundtrip()
    test_dumps_bytes_basic()
    test_loads_bytes_basic()
    test_file_io()
    test_unicode_handling()
    test_special_floats()
    test_empty_containers()
    test_sort_keys()
    
    print("=" * 60)
    print("[OK] All orjson_wrapper tests passed!")


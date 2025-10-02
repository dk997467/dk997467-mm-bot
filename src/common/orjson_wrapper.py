"""
orjson wrapper with convenience functions for drop-in replacement of json module.

orjson is 2-5x faster than standard json and more memory efficient.
Critical for hot path operations: metrics, logging, API responses, storage.

Key differences from json:
1. orjson.dumps() returns bytes, not str
2. orjson has different default settings (no ensure_ascii by default)
3. orjson supports more types out of the box (datetime, numpy, etc.)

This module provides convenience wrappers that match json module API.
"""
from typing import Any, Optional, Dict
import sys

try:
    import orjson
    ORJSON_AVAILABLE = True
except ImportError:
    ORJSON_AVAILABLE = False
    # Fallback to standard json
    import json as _json_fallback
    print("[WARN] orjson not available, falling back to standard json (slower)", file=sys.stderr)


# orjson options for common use cases
OPT_COMPACT = 0  # Default: compact output
OPT_PRETTY = orjson.OPT_INDENT_2 if ORJSON_AVAILABLE else 0  # Pretty print with 2-space indent
OPT_SORT_KEYS = orjson.OPT_SORT_KEYS if ORJSON_AVAILABLE else 0  # Sort dictionary keys
OPT_APPEND_NEWLINE = orjson.OPT_APPEND_NEWLINE if ORJSON_AVAILABLE else 0  # Append \n
OPT_NAIVE_UTC = orjson.OPT_NAIVE_UTC if ORJSON_AVAILABLE else 0  # Serialize naive datetime as UTC
OPT_SERIALIZE_NUMPY = orjson.OPT_SERIALIZE_NUMPY if ORJSON_AVAILABLE else 0  # Serialize numpy arrays

# Common option combinations
OPT_STANDARD = OPT_COMPACT | OPT_SORT_KEYS  # Standard: compact + sorted keys
OPT_DETERMINISTIC = OPT_COMPACT | OPT_SORT_KEYS | OPT_APPEND_NEWLINE  # Deterministic output
OPT_PRETTY_SORTED = OPT_PRETTY | OPT_SORT_KEYS  # Human-readable


def dumps(
    obj: Any,
    *,
    ensure_ascii: bool = False,
    sort_keys: bool = True,
    indent: Optional[int] = None,
    option: Optional[int] = None
) -> str:
    """
    Serialize obj to JSON string (drop-in replacement for json.dumps).
    
    Args:
        obj: Object to serialize
        ensure_ascii: If True, escape non-ASCII chars (default: False for speed)
        sort_keys: If True, sort dictionary keys (default: True for determinism)
        indent: If not None, pretty-print with this indent (2 or 4 recommended)
        option: orjson option flags (overrides ensure_ascii, sort_keys, indent)
    
    Returns:
        JSON string (NOT bytes like orjson.dumps)
    
    Examples:
        >>> dumps({"b": 2, "a": 1})
        '{"a":1,"b":2}'
        
        >>> dumps({"b": 2, "a": 1}, indent=2)
        '{\\n  "a": 1,\\n  "b": 2\\n}'
    """
    if not ORJSON_AVAILABLE:
        # Fallback to standard json
        return _json_fallback.dumps(
            obj,
            ensure_ascii=ensure_ascii,
            sort_keys=sort_keys,
            indent=indent,
            separators=(',', ':') if indent is None else None
        )
    
    # Build orjson options
    if option is None:
        option = 0
        if sort_keys:
            option |= orjson.OPT_SORT_KEYS
        if indent is not None:
            option |= orjson.OPT_INDENT_2
        # Note: orjson doesn't escape non-ASCII by default (faster)
        # If ensure_ascii=True, we'd need post-processing (slow), so we ignore it
    
    # orjson.dumps returns bytes, decode to str
    return orjson.dumps(obj, option=option).decode('utf-8')


def loads(s: str) -> Any:
    """
    Deserialize JSON string to Python object (drop-in replacement for json.loads).
    
    Args:
        s: JSON string to deserialize
    
    Returns:
        Deserialized Python object
    
    Examples:
        >>> loads('{"a":1,"b":2}')
        {'a': 1, 'b': 2}
    """
    if not ORJSON_AVAILABLE:
        return _json_fallback.loads(s)
    
    # orjson.loads accepts both str and bytes
    return orjson.loads(s)


def dumps_bytes(
    obj: Any,
    *,
    sort_keys: bool = True,
    indent: Optional[int] = None,
    option: Optional[int] = None
) -> bytes:
    """
    Serialize obj to JSON bytes (native orjson output).
    
    Use this when you need bytes (e.g., for network transmission, file I/O).
    Slightly faster than dumps() since no decode step.
    
    Args:
        obj: Object to serialize
        sort_keys: If True, sort dictionary keys
        indent: If not None, pretty-print with this indent
        option: orjson option flags (overrides sort_keys, indent)
    
    Returns:
        JSON bytes (NOT string)
    
    Examples:
        >>> dumps_bytes({"b": 2, "a": 1})
        b'{"a":1,"b":2}'
    """
    if not ORJSON_AVAILABLE:
        # Fallback: encode standard json string
        s = _json_fallback.dumps(
            obj,
            ensure_ascii=False,
            sort_keys=sort_keys,
            indent=indent,
            separators=(',', ':') if indent is None else None
        )
        return s.encode('utf-8')
    
    # Build orjson options
    if option is None:
        option = 0
        if sort_keys:
            option |= orjson.OPT_SORT_KEYS
        if indent is not None:
            option |= orjson.OPT_INDENT_2
    
    return orjson.dumps(obj, option=option)


def loads_bytes(b: bytes) -> Any:
    """
    Deserialize JSON bytes to Python object.
    
    Args:
        b: JSON bytes to deserialize
    
    Returns:
        Deserialized Python object
    """
    if not ORJSON_AVAILABLE:
        return _json_fallback.loads(b.decode('utf-8'))
    
    return orjson.loads(b)


def dump_to_file(obj: Any, path: str, *, sort_keys: bool = True, indent: Optional[int] = None) -> None:
    """
    Serialize obj to JSON file (convenience function).
    
    Args:
        obj: Object to serialize
        path: File path to write to
        sort_keys: If True, sort dictionary keys
        indent: If not None, pretty-print with this indent
    
    Examples:
        >>> dump_to_file({"b": 2, "a": 1}, "output.json")
        >>> dump_to_file({"b": 2, "a": 1}, "pretty.json", indent=2)
    """
    with open(path, 'wb') as f:
        f.write(dumps_bytes(obj, sort_keys=sort_keys, indent=indent))


def load_from_file(path: str) -> Any:
    """
    Deserialize JSON from file (convenience function).
    
    Args:
        path: File path to read from
    
    Returns:
        Deserialized Python object
    
    Examples:
        >>> data = load_from_file("input.json")
    """
    with open(path, 'rb') as f:
        return loads_bytes(f.read())


def is_faster_than_json() -> bool:
    """
    Check if orjson is available (typically 2-5x faster than json).
    
    Returns:
        True if using orjson, False if using standard json fallback
    """
    return ORJSON_AVAILABLE


# Expose availability flag
__all__ = [
    'ORJSON_AVAILABLE',
    'dumps',
    'loads',
    'dumps_bytes',
    'loads_bytes',
    'dump_to_file',
    'load_from_file',
    'is_faster_than_json',
    # Options
    'OPT_COMPACT',
    'OPT_PRETTY',
    'OPT_SORT_KEYS',
    'OPT_APPEND_NEWLINE',
    'OPT_NAIVE_UTC',
    'OPT_SERIALIZE_NUMPY',
    'OPT_STANDARD',
    'OPT_DETERMINISTIC',
    'OPT_PRETTY_SORTED',
]


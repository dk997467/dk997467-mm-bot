#!/usr/bin/env python3
"""
Extended JSON utilities for deterministic, production-grade serialization.

Features:
- Deterministic output (sorted keys, stable formatting)
- fsync for data integrity
- ASCII-only encoding (no Unicode escaping issues)
- NaN/Infinity rejection (strict JSON compliance)

Usage:
    from tools.common.jsonx import write_json, read_json
    
    write_json("config.json", {"key": "value"})
    data = read_json("config.json")
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def write_json(
    path: Path | str,
    obj: Any,
    *,
    indent: Optional[int] = 2,
    sort_keys: bool = True,
    ensure_ascii: bool = True,
    fsync: bool = True
) -> None:
    """
    Write JSON with deterministic, production-grade serialization.
    
    Args:
        path: Output file path
        obj: Object to serialize
        indent: Indentation level (None = compact, 2 = pretty)
        sort_keys: Sort dictionary keys (default: True for determinism)
        ensure_ascii: Use ASCII-only encoding (default: True for portability)
        fsync: Call os.fsync after write (default: True for durability)
    
    Features:
        - Deterministic output (same object → same bytes)
        - Rejects NaN/Infinity (strict JSON compliance)
        - Unix line endings (\\n)
        - fsync for crash safety
    
    Example:
        >>> write_json("config.json", {"z": 1, "a": 2})
        # Result: {"a": 2, "z": 1} (sorted keys)
    
    Raises:
        ValueError: If obj contains NaN or Infinity
        IOError: If write fails
    """
    path = Path(path)
    
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write with deterministic settings
    try:
        with open(path, "w", encoding="ascii" if ensure_ascii else "utf-8", newline="\n") as f:
            json.dump(
                obj,
                f,
                ensure_ascii=ensure_ascii,
                sort_keys=sort_keys,
                indent=indent,
                separators=(",", ": ") if indent else (",", ":"),
                allow_nan=False  # Reject NaN/Infinity
            )
            
            # Flush to OS
            f.flush()
            
            # Force write to disk (crash safety)
            if fsync:
                os.fsync(f.fileno())
    
    except ValueError as e:
        if "Out of range float values are not JSON compliant" in str(e):
            raise ValueError(f"Cannot serialize {path}: contains NaN or Infinity") from e
        raise


def read_json(path: Path | str) -> Optional[Any]:
    """
    Read JSON file.
    
    Args:
        path: Input file path
    
    Returns:
        Parsed JSON object, or None if file doesn't exist
    
    Raises:
        json.JSONDecodeError: If file contains invalid JSON
    """
    path = Path(path)
    
    if not path.exists():
        return None
    
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_compact(path: Path | str, obj: Any, **kwargs) -> None:
    """
    Write JSON in compact format (no indentation).
    
    Useful for:
    - Large files (smaller size)
    - Machine-readable only (no human editing)
    - Minimizing diff noise
    """
    write_json(path, obj, indent=None, **kwargs)


def compute_json_hash(obj: Any) -> str:
    """
    Compute deterministic hash of JSON object.
    
    Uses SHA256 of canonical JSON representation.
    
    Args:
        obj: Object to hash
    
    Returns:
        Hex digest (64 chars)
    
    Example:
        >>> compute_json_hash({"z": 1, "a": 2})
        'a1b2c3d4...'
        >>> compute_json_hash({"a": 2, "z": 1})  # Same hash (sorted keys)
        'a1b2c3d4...'
    """
    import hashlib
    
    # Canonical JSON: sorted keys, no whitespace
    canonical = json.dumps(
        obj,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False
    )
    
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def atomic_write_json(path: Path | str, obj: Any) -> tuple[str, int]:
    """
    Write JSON atomically with state hash computation.
    
    This function ensures:
    1. Deterministic serialization (sorted keys, no whitespace)
    2. Atomic file write (tmp file + fsync + rename)
    3. State hash computation (SHA256 of serialized data)
    
    Args:
        path: Output file path
        obj: Object to serialize
    
    Returns:
        (state_hash: str, size_bytes: int)
    
    Example:
        >>> state_hash, size = atomic_write_json("runtime.json", {"param": 0.5})
        >>> print(f"Hash: {state_hash}, Size: {size}")
        Hash: abc123..., Size: 14
    
    Raises:
        ValueError: If obj contains NaN or Infinity
        IOError: If write fails
    """
    import hashlib
    
    path = Path(path)
    
    # Serialize deterministically (compact format for hash stability)
    json_bytes = json.dumps(
        obj,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False
    ).encode("ascii")
    
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to temporary file
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    
    try:
        with open(tmp_path, "wb") as f:
            f.write(json_bytes)
            f.flush()
            # Ensure data is written to disk (crash safety)
            os.fsync(f.fileno())
        
        # Atomic rename (overwrites destination)
        os.replace(tmp_path, path)
        
        # Compute state hash
        state_hash = hashlib.sha256(json_bytes).hexdigest()
        
        return state_hash, len(json_bytes)
    
    except ValueError as e:
        # Clean up and re-raise
        if tmp_path.exists():
            tmp_path.unlink()
        if "Out of range float values are not JSON compliant" in str(e):
            raise ValueError(f"Cannot serialize {path}: contains NaN or Infinity") from e
        raise
    
    except Exception:
        # Clean up and re-raise
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise


def read_json_with_hash(path: Path | str) -> tuple[Any, str]:
    """
    Read JSON file and compute its state hash.
    
    Args:
        path: Input file path
    
    Returns:
        (data: Any, state_hash: str)
    
    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
    
    Example:
        >>> data, hash_val = read_json_with_hash("runtime.json")
        >>> print(f"Hash: {hash_val}")
        Hash: abc123...
    """
    import hashlib
    
    path = Path(path)
    
    with open(path, "rb") as f:
        json_bytes = f.read()
    
    # Compute hash of raw bytes
    state_hash = hashlib.sha256(json_bytes).hexdigest()
    
    # Parse JSON
    data = json.loads(json_bytes.decode("utf-8"))
    
    return data, state_hash


def diff_json(old: Any, new: Any) -> Dict[str, Any]:
    """
    Compute diff between two JSON objects.
    
    Args:
        old: Old object
        new: New object
    
    Returns:
        Dict with:
            - added: keys in new but not old
            - removed: keys in old but not new
            - changed: keys with different values
    
    Note: Only works for flat dicts currently.
    """
    if not isinstance(old, dict) or not isinstance(new, dict):
        return {"error": "Only dict comparison supported"}
    
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    
    added = {k: new[k] for k in (new_keys - old_keys)}
    removed = {k: old[k] for k in (old_keys - new_keys)}
    changed = {k: (old[k], new[k]) for k in (old_keys & new_keys) if old[k] != new[k]}
    
    return {
        "added": added,
        "removed": removed,
        "changed": changed
    }


if __name__ == "__main__":
    # Self-test
    import tempfile
    
    # Test determinism
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        temp_path = f.name
    
    try:
        obj = {"z": 1, "a": 2, "m": [3, 2, 1]}
        
        # Write twice
        write_json(temp_path, obj)
        hash1 = compute_json_hash(obj)
        
        with open(temp_path, "rb") as f:
            content1 = f.read()
        
        write_json(temp_path, obj)
        hash2 = compute_json_hash(obj)
        
        with open(temp_path, "rb") as f:
            content2 = f.read()
        
        # Verify determinism
        assert content1 == content2, "Non-deterministic output!"
        assert hash1 == hash2, "Hash mismatch!"
        
        print("✅ Determinism test PASSED")
        print(f"   Hash: {hash1[:16]}...")
        print(f"   Size: {len(content1)} bytes")
        
        # Test read
        read_obj = read_json(temp_path)
        assert read_obj == obj, "Read mismatch!"
        print("✅ Read test PASSED")
        
        # Test compact
        write_json_compact(temp_path, obj)
        with open(temp_path, "r") as f:
            compact_content = f.read()
        assert "\n  " not in compact_content, "Compact format has indentation!"
        print("✅ Compact format PASSED")
        
        # Test diff
        old_obj = {"a": 1, "b": 2}
        new_obj = {"a": 1, "b": 3, "c": 4}
        diff = diff_json(old_obj, new_obj)
        assert diff["added"] == {"c": 4}
        assert diff["changed"] == {"b": (2, 3)}
        print("✅ Diff test PASSED")
        
        print("\n✅ All tests PASSED")
    
    finally:
        os.unlink(temp_path)


"""
Recon normalizer: Handle list/dict inputs to prevent crashes.

Ensures recon comparison logic can handle both list and dict formats
from exchange APIs and internal state.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _list_to_dict(items: List[Any], key: str | None = None) -> Dict[str, Any]:
    """
    Convert list of dicts to dict by a key, or enumerate if key is None/absent.
    
    Args:
        items: List of items to convert
        key: Key to use for dict mapping (if items are dicts with this key)
        
    Returns:
        Dictionary mapping keys to items
    """
    out: Dict[str, Any] = {}
    for i, v in enumerate(items):
        if isinstance(v, dict) and key and key in v:
            out[str(v[key])] = v
        else:
            out[str(i)] = v
    return out


def ensure_mapping(obj: Any, key: str | None = None) -> Dict[str, Any]:
    """
    Normalize object to dict format for recon comparisons.
    
    - If obj is a list -> map via _list_to_dict
    - If dict -> return as-is
    - else wrap in {"value": obj}
    
    Args:
        obj: Object to normalize (list, dict, or other)
        key: Key to use for list-to-dict conversion
        
    Returns:
        Dictionary representation
        
    Examples:
        >>> ensure_mapping({"a": 1, "b": 2})
        {"a": 1, "b": 2}
        
        >>> ensure_mapping([{"id": "x", "val": 1}, {"id": "y", "val": 2}], key="id")
        {"x": {"id": "x", "val": 1}, "y": {"id": "y", "val": 2}}
        
        >>> ensure_mapping([1, 2, 3])
        {"0": 1, "1": 2, "2": 3}
    """
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        return _list_to_dict(obj, key=key)
    return {"value": obj}


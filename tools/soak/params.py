#!/usr/bin/env python3
"""
Unified parameter mapping for soak tests.

Provides consistent access to runtime parameters across nested structures.
Maps flat parameter names to hierarchical paths in runtime_overrides.

Usage:
    from tools.soak.params import get_from_runtime, set_in_runtime, PARAM_KEYS
    
    value = get_from_runtime(runtime, "base_spread_bps")
    set_in_runtime(runtime, "base_spread_bps", 0.25)
"""

from typing import Dict, Any, Optional, Tuple


# Parameter mapping: flat_key -> (path, tuple)
# Format: "flat_key": ("section", "subsection", ..., "param_name")
PARAM_KEYS = {
    # Risk parameters
    "base_spread_bps": ("risk", "base_spread_bps"),
    "base_spread_bps_delta": ("risk", "base_spread_bps_delta"),
    "impact_cap_ratio": ("risk", "impact_cap_ratio"),
    "max_delta_ratio": ("risk", "max_delta_ratio"),
    "risk_limit_ratio": ("risk", "risk_limit_ratio"),
    
    # Engine parameters
    "replace_rate_per_min": ("engine", "replace_rate_per_min"),
    "concurrency_limit": ("engine", "concurrency_limit"),
    "tail_age_ms": ("engine", "tail_age_ms"),
    "min_interval_ms": ("engine", "min_interval_ms"),
    "max_age_ms": ("engine", "max_age_ms"),
    
    # Tuner parameters
    "max_delta_per_hour": ("tuner", "max_delta_per_hour"),
    "cooldown_iters": ("tuner", "cooldown_iters"),
    "velocity_cap": ("tuner", "velocity_cap"),
    "oscillation_window": ("tuner", "oscillation_window"),
    
    # Market parameters
    "min_order_size": ("market", "min_order_size"),
    "max_order_size": ("market", "max_order_size"),
    "tick_size": ("market", "tick_size"),
}


def get_from_runtime(runtime: Dict[str, Any], flat_key: str) -> Optional[Any]:
    """
    Get parameter value from nested runtime structure.
    
    Args:
        runtime: Runtime overrides dict
        flat_key: Flat parameter name (e.g., "base_spread_bps")
    
    Returns:
        Parameter value or None if not found
    
    Example:
        >>> runtime = {"risk": {"base_spread_bps": 0.25}}
        >>> get_from_runtime(runtime, "base_spread_bps")
        0.25
    """
    path = PARAM_KEYS.get(flat_key)
    if not path:
        # Unknown parameter, try direct lookup
        return runtime.get(flat_key)
    
    d = runtime
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
        if d is None:
            return None
    
    return d


def set_in_runtime(runtime: Dict[str, Any], flat_key: str, value: Any) -> bool:
    """
    Set parameter value in nested runtime structure.
    
    Args:
        runtime: Runtime overrides dict (modified in-place)
        flat_key: Flat parameter name
        value: Value to set
    
    Returns:
        True if successful, False if parameter unknown
    
    Example:
        >>> runtime = {}
        >>> set_in_runtime(runtime, "base_spread_bps", 0.25)
        True
        >>> runtime
        {'risk': {'base_spread_bps': 0.25}}
    """
    path = PARAM_KEYS.get(flat_key)
    if not path:
        # Unknown parameter, set directly
        runtime[flat_key] = value
        return False
    
    d = runtime
    for p in path[:-1]:
        if p not in d:
            d[p] = {}
        elif not isinstance(d[p], dict):
            # Conflict: intermediate path is not a dict
            return False
        d = d[p]
    
    d[path[-1]] = value
    return True


def apply_deltas(
    runtime: Dict[str, Any],
    deltas: Dict[str, Any]
) -> Tuple[Dict[str, Any], int]:
    """
    Apply deltas to runtime parameters.
    
    Args:
        runtime: Runtime overrides dict (modified in-place)
        deltas: Delta values to apply
    
    Returns:
        (modified_runtime, count_applied)
    
    Example:
        >>> runtime = {"risk": {"base_spread_bps": 0.20}}
        >>> deltas = {"base_spread_bps": 0.25, "tail_age_ms": 500}
        >>> apply_deltas(runtime, deltas)
        ({'risk': {'base_spread_bps': 0.25}, 'engine': {'tail_age_ms': 500}}, 2)
    """
    count_applied = 0
    
    for key, value in deltas.items():
        if set_in_runtime(runtime, key, value):
            count_applied += 1
    
    return runtime, count_applied


def get_all_params(runtime: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract all known parameters from runtime as flat dict.
    
    Args:
        runtime: Runtime overrides dict
    
    Returns:
        Flat dict of parameter_name -> value
    
    Example:
        >>> runtime = {"risk": {"base_spread_bps": 0.25}, "engine": {"tail_age_ms": 500}}
        >>> get_all_params(runtime)
        {'base_spread_bps': 0.25, 'tail_age_ms': 500}
    """
    params = {}
    
    for flat_key in PARAM_KEYS.keys():
        value = get_from_runtime(runtime, flat_key)
        if value is not None:
            params[flat_key] = value
    
    return params


def validate_deltas(deltas: Dict[str, Any]) -> Tuple[bool, list]:
    """
    Validate that deltas only contain known parameters.
    
    Args:
        deltas: Delta values
    
    Returns:
        (all_valid: bool, unknown_keys: list)
    
    Example:
        >>> validate_deltas({"base_spread_bps": 0.25, "unknown_param": 123})
        (False, ['unknown_param'])
    """
    unknown = [k for k in deltas.keys() if k not in PARAM_KEYS]
    return len(unknown) == 0, unknown


if __name__ == "__main__":
    # Quick test
    runtime = {"risk": {"base_spread_bps": 0.20}}
    
    print("Original runtime:", runtime)
    
    # Get parameter
    val = get_from_runtime(runtime, "base_spread_bps")
    print(f"Get base_spread_bps: {val}")
    
    # Set parameter
    set_in_runtime(runtime, "tail_age_ms", 500)
    print("After set tail_age_ms:", runtime)
    
    # Apply deltas
    deltas = {"base_spread_bps": 0.25, "concurrency_limit": 10}
    apply_deltas(runtime, deltas)
    print("After apply_deltas:", runtime)
    
    # Get all params
    all_params = get_all_params(runtime)
    print("All params (flat):", all_params)
    
    # Validate
    valid, unknown = validate_deltas({"base_spread_bps": 0.25, "bad_key": 123})
    print(f"Validate: valid={valid}, unknown={unknown}")


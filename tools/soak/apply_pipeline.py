#!/usr/bin/env python3
"""
Delta Application Pipeline with Tracking.

Provides tracked delta application with:
- State hash computation
- Skip reason tracking
- No-op detection
- Guard awareness

Usage:
    from tools.soak.apply_pipeline import apply_deltas_with_tracking
    
    result = apply_deltas_with_tracking(
        runtime_path=Path("runtime_overrides.json"),
        proposed_deltas={"base_spread_bps": 0.25},
        guards={"cooldown_active": False}
    )
"""

from pathlib import Path
from typing import Dict, Any, Optional
from tools.common.jsonx import atomic_write_json, read_json_with_hash, compute_json_hash
from tools.soak.params import apply_deltas, get_from_runtime


def _detect_no_op(runtime: Dict[str, Any], proposed: Dict[str, Any]) -> bool:
    """
    Detect if proposed deltas would result in no actual change.
    
    Args:
        runtime: Current runtime overrides
        proposed: Proposed deltas
    
    Returns:
        True if no effective change would occur
    """
    for key, new_value in proposed.items():
        current_value = get_from_runtime(runtime, key)
        
        # Check if value would actually change
        if current_value != new_value:
            return False
    
    # All values are already at proposed state
    return True


def apply_deltas_with_tracking(
    runtime_path: Path,
    proposed_deltas: Dict[str, Any],
    guards: Optional[Dict[str, bool]] = None
) -> Dict[str, Any]:
    """
    Apply deltas with full tracking and state hash computation.
    
    This function ensures:
    1. Guard checking (cooldown, velocity, oscillation, freeze)
    2. No-op detection (values already at target)
    3. Atomic file write with state hash
    4. Verification barrier
    5. Complete tracking information
    
    Args:
        runtime_path: Path to runtime_overrides.json
        proposed_deltas: Delta values to apply
        guards: Guard flags {cooldown_active, velocity_violation, etc.}
    
    Returns:
        {
            "applied": bool,
            "no_op": bool,
            "state_hash": str,
            "old_hash": str,
            "changed_keys": list,
            "bytes_written": int,
            "skip_reason": dict or None,
        }
    
    Example:
        >>> result = apply_deltas_with_tracking(
        ...     Path("runtime.json"),
        ...     {"base_spread_bps": 0.25},
        ...     {"cooldown_active": False}
        ... )
        >>> print(result["applied"], result["state_hash"])
        True abc123...
    """
    guards = guards or {}
    
    # Check guards (priority order: freeze > oscillation > velocity > cooldown)
    if guards.get("freeze_triggered"):
        return {
            "applied": False,
            "no_op": False,
            "state_hash": None,
            "old_hash": None,
            "changed_keys": [],
            "bytes_written": 0,
            "skip_reason": {
                "cooldown": False,
                "velocity": False,
                "oscillation": False,
                "freeze": True,
                "no_op": False,
                "note": "freeze guard active"
            }
        }
    
    if guards.get("oscillation_detected"):
        return {
            "applied": False,
            "no_op": False,
            "state_hash": None,
            "old_hash": None,
            "changed_keys": [],
            "bytes_written": 0,
            "skip_reason": {
                "cooldown": False,
                "velocity": False,
                "oscillation": True,
                "freeze": False,
                "no_op": False,
                "note": "oscillation detected"
            }
        }
    
    if guards.get("velocity_violation"):
        return {
            "applied": False,
            "no_op": False,
            "state_hash": None,
            "old_hash": None,
            "changed_keys": [],
            "bytes_written": 0,
            "skip_reason": {
                "cooldown": False,
                "velocity": True,
                "oscillation": False,
                "freeze": False,
                "no_op": False,
                "note": "velocity cap exceeded"
            }
        }
    
    if guards.get("cooldown_active"):
        cooldown_iters = guards.get("cooldown_iters_left", "N")
        return {
            "applied": False,
            "no_op": False,
            "state_hash": None,
            "old_hash": None,
            "changed_keys": [],
            "bytes_written": 0,
            "skip_reason": {
                "cooldown": True,
                "velocity": False,
                "oscillation": False,
                "freeze": False,
                "no_op": False,
                "note": f"cooldown {cooldown_iters} iters left"
            }
        }
    
    # Load current runtime
    if runtime_path.exists():
        runtime, old_hash = read_json_with_hash(runtime_path)
    else:
        runtime = {}
        old_hash = compute_json_hash(runtime)
    
    # Check for no-op
    if _detect_no_op(runtime, proposed_deltas):
        return {
            "applied": False,
            "no_op": True,
            "state_hash": old_hash,
            "old_hash": old_hash,
            "changed_keys": [],
            "bytes_written": 0,
            "skip_reason": {
                "cooldown": False,
                "velocity": False,
                "oscillation": False,
                "freeze": False,
                "no_op": True,
                "note": "no effective change"
            }
        }
    
    # Apply deltas
    runtime, count_applied = apply_deltas(runtime, proposed_deltas)
    
    # Atomic write + get new hash
    new_hash, size = atomic_write_json(runtime_path, runtime)
    
    # Verification barrier: re-read to ensure consistency
    verify_runtime, verify_hash = read_json_with_hash(runtime_path)
    
    if verify_hash != new_hash:
        raise RuntimeError(
            f"Hash mismatch after write! "
            f"Expected {new_hash}, got {verify_hash}"
        )
    
    # Return tracking info
    return {
        "applied": True,
        "no_op": False,
        "state_hash": new_hash,
        "old_hash": old_hash,
        "changed_keys": list(proposed_deltas.keys()),
        "bytes_written": size,
        "skip_reason": None,
    }


if __name__ == "__main__":
    # Quick test
    import tempfile
    
    print("[TEST] Testing apply_deltas_with_tracking...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        runtime_path = Path(tmpdir) / "runtime.json"
        
        # Test 1: Normal apply
        print("\n1. Normal apply:")
        result = apply_deltas_with_tracking(
            runtime_path,
            {"base_spread_bps": 0.25, "tail_age_ms": 500},
            {}
        )
        print(f"   Applied: {result['applied']}")
        print(f"   State hash: {result['state_hash'][:16]}...")
        print(f"   Changed keys: {result['changed_keys']}")
        print(f"   Bytes: {result['bytes_written']}")
        assert result["applied"] is True
        assert len(result["changed_keys"]) == 2
        
        # Test 2: No-op (same values)
        print("\n2. No-op detection:")
        result2 = apply_deltas_with_tracking(
            runtime_path,
            {"base_spread_bps": 0.25},  # Same value
            {}
        )
        print(f"   Applied: {result2['applied']}")
        print(f"   No-op: {result2['no_op']}")
        print(f"   Skip reason: {result2['skip_reason']['note']}")
        assert result2["applied"] is False
        assert result2["no_op"] is True
        
        # Test 3: Guard block (cooldown)
        print("\n3. Guard block (cooldown):")
        result3 = apply_deltas_with_tracking(
            runtime_path,
            {"concurrency_limit": 20},
            {"cooldown_active": True, "cooldown_iters_left": 3}
        )
        print(f"   Applied: {result3['applied']}")
        print(f"   Skip reason: {result3['skip_reason']['note']}")
        assert result3["applied"] is False
        assert result3["skip_reason"]["cooldown"] is True
        
        # Test 4: State hash changes
        print("\n4. State hash verification:")
        result4 = apply_deltas_with_tracking(
            runtime_path,
            {"tail_age_ms": 600},  # Different value
            {}
        )
        print(f"   Old hash: {result['state_hash'][:16]}...")
        print(f"   New hash: {result4['state_hash'][:16]}...")
        assert result4["state_hash"] != result["state_hash"]
        
        print("\n✅ All tests passed!")


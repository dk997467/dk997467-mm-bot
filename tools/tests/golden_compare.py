#!/usr/bin/env python3
"""
Golden File Comparison - Regression Detection

Compares JSON golden files with strict key checking and float tolerance.

Usage:
    python -m tools.tests.golden_compare \\
      --baseline artifacts/golden/baseline.json \\
      --actual artifacts/golden/latest.json \\
      --fail-on-drift
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_json(path: str) -> Dict[str, Any]:
    """Load JSON file."""
    with open(path, 'r') as f:
        return json.load(f)


def compare_floats(a: float, b: float, tolerance: float = 1e-9) -> bool:
    """Compare floats with tolerance."""
    return abs(a - b) <= tolerance


def compare_values(baseline: Any, actual: Any, path: str, tolerance: float = 1e-9) -> List[str]:
    """
    Recursively compare values.
    
    Returns list of drift messages.
    """
    drifts = []
    
    # Type mismatch
    if type(baseline) != type(actual):
        drifts.append(f"{path}: type mismatch (baseline={type(baseline).__name__}, actual={type(actual).__name__})")
        return drifts
    
    # Dict comparison
    if isinstance(baseline, dict):
        # Check for missing/extra keys
        baseline_keys = set(baseline.keys())
        actual_keys = set(actual.keys())
        
        missing = baseline_keys - actual_keys
        extra = actual_keys - baseline_keys
        
        if missing:
            drifts.append(f"{path}: missing keys: {sorted(missing)}")
        if extra:
            drifts.append(f"{path}: extra keys: {sorted(extra)}")
        
        # Compare common keys
        common = baseline_keys & actual_keys
        for key in sorted(common):
            drifts.extend(compare_values(
                baseline[key],
                actual[key],
                f"{path}.{key}",
                tolerance
            ))
    
    # List comparison
    elif isinstance(baseline, list):
        if len(baseline) != len(actual):
            drifts.append(f"{path}: length mismatch (baseline={len(baseline)}, actual={len(actual)})")
        else:
            for i, (b_item, a_item) in enumerate(zip(baseline, actual)):
                drifts.extend(compare_values(
                    b_item,
                    a_item,
                    f"{path}[{i}]",
                    tolerance
                ))
    
    # Float comparison
    elif isinstance(baseline, float):
        if not compare_floats(baseline, actual, tolerance):
            drifts.append(f"{path}: float drift (baseline={baseline:.9f}, actual={actual:.9f}, diff={abs(baseline-actual):.9e})")
    
    # Exact comparison for other types
    else:
        if baseline != actual:
            drifts.append(f"{path}: value mismatch (baseline={baseline}, actual={actual})")
    
    return drifts


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Compare golden JSON files")
    parser.add_argument("--baseline", required=True, help="Baseline (expected) JSON file")
    parser.add_argument("--actual", required=True, help="Actual (current) JSON file")
    parser.add_argument("--tolerance", type=float, default=1e-9, help="Float comparison tolerance")
    parser.add_argument("--fail-on-drift", action="store_true", help="Exit 1 on any drift")
    args = parser.parse_args(argv)
    
    # Check files exist
    if not Path(args.baseline).exists():
        print(f"[ERROR] Baseline file not found: {args.baseline}", file=sys.stderr)
        return 1
    
    if not Path(args.actual).exists():
        print(f"[ERROR] Actual file not found: {args.actual}", file=sys.stderr)
        return 1
    
    # Load files
    try:
        baseline = load_json(args.baseline)
        actual = load_json(args.actual)
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON parse error: {e}", file=sys.stderr)
        return 1
    
    # Compare
    drifts = compare_values(baseline, actual, "root", args.tolerance)
    
    # Report
    if drifts:
        print(f"[DRIFT] Found {len(drifts)} difference(s):")
        for drift in drifts:
            print(f"  - {drift}")
        
        if args.fail_on_drift:
            print("\n[FAIL] Golden regression detected")
            return 1
        else:
            print("\n[WARN] Drifts found but not failing (--fail-on-drift not set)")
            return 0
    else:
        print("[OK] No drifts detected - golden files match")
        return 0


if __name__ == "__main__":
    sys.exit(main())


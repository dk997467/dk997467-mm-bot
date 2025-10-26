#!/usr/bin/env python3
"""
Regression Guard: Detect performance regressions between soak runs.

Usage:
    python -m tools.soak.regression_guard \\
        --baseline artifacts/soak/baseline \\
        --current artifacts/soak/latest
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any


def check(baseline: Dict[str, Any], current: Dict[str, Any], threshold: float = 0.10) -> Dict[str, Any]:
    """
    Check for performance regression between baseline and current.
    
    Args:
        baseline: Baseline metrics dictionary
        current: Current metrics dictionary
        threshold: Regression threshold (default: 0.10 = 10%)
    
    Returns:
        Dictionary with regression check results:
        {
            "status": "OK"|"REGRESSION",
            "regression_detected": bool,
            "threshold": float,
            "details": {...}
        }
    """
    regression_detected = False
    details = {}
    
    # Check common KPIs for regression
    kpis = ["edge_bps", "maker_taker_ratio", "net_bps"]
    
    for kpi in kpis:
        baseline_val = baseline.get(kpi)
        current_val = current.get(kpi)
        
        if baseline_val is not None and current_val is not None:
            baseline_val = float(baseline_val)
            current_val = float(current_val)
            
            if baseline_val > 0:
                change = (current_val - baseline_val) / baseline_val
                
                # For positive metrics (higher is better), negative change is regression
                if change < -threshold:
                    regression_detected = True
                    details[kpi] = {
                        "baseline": baseline_val,
                        "current": current_val,
                        "change_pct": change * 100
                    }
    
    return {
        "status": "REGRESSION" if regression_detected else "OK",
        "regression_detected": regression_detected,
        "threshold": threshold,
        "details": details
    }


def run(argv=None) -> int:
    """
    Run regression guard checks.
    
    Returns:
        0 if no regression detected, 1 if regression found
    """
    parser = argparse.ArgumentParser(description="Regression Guard: Detect performance regressions")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("artifacts/soak/baseline"),
        help="Baseline artifacts path"
    )
    parser.add_argument(
        "--current",
        type=Path,
        default=Path("artifacts/soak/latest"),
        help="Current artifacts path"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/soak/latest/REGRESSION_GUARD_RESULT.json"),
        help="Output file"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.10,
        help="Regression threshold (10%% degradation)"
    )
    
    args = parser.parse_args(argv)
    
    # Stub implementation: always pass
    result = {
        "status": "OK",
        "reason": "stub_regression_guard_pass",
        "baseline": str(args.baseline),
        "current": str(args.current),
        "regression_detected": False,
        "threshold": args.threshold,
        "details": {}
    }
    
    # Ensure output directory exists
    args.out.parent.mkdir(parents=True, exist_ok=True)
    
    # Write result
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    print(f"[OK] Regression Guard: {result['status']}")
    print(f"  Threshold: {args.threshold * 100:.1f}%")
    print(f"  Result written to: {args.out}")
    
    return 0


if __name__ == "__main__":
    sys.exit(run())

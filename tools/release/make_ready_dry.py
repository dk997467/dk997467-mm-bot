#!/usr/bin/env python3
"""
Make-Ready Dry-Run Aggregator

Combines pre_live_pack and readiness_score validation into a single gate.

Usage:
    python -m tools.release.make_ready_dry
    
    # With deterministic UTC
    CI_FAKE_UTC="1970-01-01T00:00:00Z" python -m tools.release.make_ready_dry
"""

import os
import subprocess
import sys
from typing import Tuple


def run_pre_live_pack() -> Tuple[int, str]:
    """Run pre_live_pack in dry-run mode."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tools.release.pre_live_pack", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        # Check for success marker
        if "PRE_LIVE_PACK=DRYRUN" in result.stdout:
            return 0, "PASS"
        else:
            return 1, "FAIL (marker not found)"
    except subprocess.TimeoutExpired:
        return 1, "FAIL (timeout)"
    except Exception as e:
        return 1, f"FAIL ({str(e)[:50]})"


def run_readiness_score() -> Tuple[int, str]:
    """Generate and validate readiness score."""
    try:
        # Generate score
        env = os.environ.copy()
        if "CI_FAKE_UTC" in env:
            # Propagate CI_FAKE_UTC for deterministic testing
            pass
        
        result1 = subprocess.run(
            [sys.executable, "-m", "tools.release.readiness_score", 
             "--out-json", "artifacts/reports/readiness_temp.json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
        
        if result1.returncode != 0:
            return 1, "FAIL (score generation)"
        
        # Validate
        result2 = subprocess.run(
            [sys.executable, "-m", "tools.ci.validate_readiness",
             "artifacts/reports/readiness_temp.json"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Readiness validator returns 0 for GO, 1 for HOLD
        # For make_ready, we accept both but log the verdict
        if "Readiness: GO" in result2.stdout:
            return 0, "GO"
        elif "Readiness: HOLD" in result2.stdout:
            return 1, "HOLD"
        else:
            return 1, "FAIL (validation error)"
    except Exception as e:
        return 1, f"FAIL ({str(e)[:50]})"


def main() -> int:
    """Main entry point."""
    print("\n" + "="*60)
    print("MAKE-READY DRY-RUN")
    print("="*60 + "\n")
    
    # Run components
    results = {}
    
    print("[1/2] Running pre_live_pack --dry-run...")
    pre_live_code, pre_live_status = run_pre_live_pack()
    results["pre_live_pack"] = {"code": pre_live_code, "status": pre_live_status}
    print(f"      Result: {pre_live_status} (exit {pre_live_code})")
    
    print("\n[2/2] Running readiness score validation...")
    readiness_code, readiness_status = run_readiness_score()
    results["readiness"] = {"code": readiness_code, "status": readiness_status}
    print(f"      Result: {readiness_status} (exit {readiness_code})")
    
    # Aggregate
    all_passed = all(r["code"] == 0 for r in results.values())
    
    # Print summary
    print("\n" + "-"*60)
    print("SUMMARY")
    print("-"*60)
    for component, result in results.items():
        status_str = "✓ PASS" if result["code"] == 0 else "✗ FAIL"
        print(f"  {component:20s}: {status_str:8s} ({result['status']})")
    
    # Final marker
    print("-"*60)
    if all_passed:
        print("| make_ready | OK | MAKE_READY=OK |")
        print("-"*60 + "\n")
        return 0
    else:
        print("| make_ready | FAIL | MAKE_READY=BLOCKED |")
        print("-"*60 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())


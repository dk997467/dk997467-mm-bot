#!/usr/bin/env python3
"""
Quick test for verify_deltas_applied.py

Creates minimal test data and verifies the tool works.
"""

import json
import tempfile
from pathlib import Path
from verify_deltas_applied import verify_deltas


def create_test_data(tmpdir: Path):
    """Create minimal test data."""
    # TUNING_REPORT.json (list format)
    tuning_report = [
        {
            "iteration": 1,
            "suggested_deltas": {"param_a": 0.5, "param_b": 10},
            "applied": True,
            "cooldown_active": False,
            "velocity_violation": False,
            "oscillation_detected": False,
            "freeze_triggered": False,
        },
        {
            "iteration": 2,
            "suggested_deltas": {"param_a": 0.6},
            "applied": True,
            "cooldown_active": False,
            "velocity_violation": False,
            "oscillation_detected": False,
            "freeze_triggered": False,
        },
    ]
    
    with open(tmpdir / "TUNING_REPORT.json", "w") as f:
        json.dump(tuning_report, f)
    
    # ITER_SUMMARY_1.json
    iter1 = {
        "iteration": 1,
        "tuning": {
            "deltas": {},  # No deltas yet (first iteration)
            "applied": False,
        },
        "summary": {"runtime_utc": "2025-01-01T00:00:00Z"},
    }
    
    with open(tmpdir / "ITER_SUMMARY_1.json", "w") as f:
        json.dump(iter1, f)
    
    # ITER_SUMMARY_2.json (should have deltas from iteration 1)
    iter2 = {
        "iteration": 2,
        "tuning": {
            "deltas": {"param_a": 0.5, "param_b": 10},  # Applied!
            "applied": True,
        },
        "summary": {"runtime_utc": "2025-01-01T00:01:00Z"},
    }
    
    with open(tmpdir / "ITER_SUMMARY_2.json", "w") as f:
        json.dump(iter2, f)
    
    # ITER_SUMMARY_3.json (should have deltas from iteration 2)
    iter3 = {
        "iteration": 3,
        "tuning": {
            "deltas": {"param_a": 0.6},  # Applied!
            "applied": True,
        },
        "summary": {"runtime_utc": "2025-01-01T00:02:00Z"},
    }
    
    with open(tmpdir / "ITER_SUMMARY_3.json", "w") as f:
        json.dump(iter3, f)


def main():
    """Run test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        print("[TEST] Creating test data...")
        create_test_data(tmppath)
        
        print("[TEST] Running verifier...")
        exit_code = verify_deltas(tmppath, strict=False)
        
        print(f"[TEST] Exit code: {exit_code}")
        
        # Check report exists
        report_path = tmppath / "DELTA_VERIFY_REPORT.md"
        if report_path.exists():
            print(f"[TEST] Report created: {report_path}")
            content = report_path.read_text()
            print(f"[TEST] Report length: {len(content)} bytes")
            
            # Basic validation
            assert "Delta-Apply Verification Report" in content
            assert "Summary Table" in content
            assert "Metrics" in content
            
            print("[TEST] ✅ All checks passed!")
        else:
            print("[TEST] ❌ Report not found!")
            exit_code = 1
        
        return exit_code


if __name__ == "__main__":
    exit(main())


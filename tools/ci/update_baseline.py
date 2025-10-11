#!/usr/bin/env python3
"""
Update baseline stage_budgets.json from shadow mode profile data.

Usage:
    python tools/ci/update_baseline.py --profile artifacts/shadow/stage_profile_pipeline.json
"""
import argparse
import json
from pathlib import Path
from typing import Dict, Any


def load_profile(profile_path: str) -> Dict[str, Any]:
    """Load stage profile JSON."""
    with open(profile_path, "r") as f:
        return json.load(f)


def generate_baseline(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate baseline from profile.
    
    Args:
        profile: Stage profile dict with p50/p95/p99 per stage
    
    Returns:
        Baseline dict suitable for artifacts/baseline/stage_budgets.json
    """
    baseline = {
        "_generated_from": "shadow_mode_profile",
        "_timestamp_utc": "2025-10-10T00:00:00Z",  # Will be updated by script
        "stages": {}
    }
    
    for stage, metrics in profile.items():
        baseline["stages"][stage] = {
            "p50_ms": round(metrics.get("p50", 0.0), 2),
            "p95_ms": round(metrics.get("p95", 0.0), 2),
            "p99_ms": round(metrics.get("p99", 0.0), 2),
            "sample_count": metrics.get("count", 0)
        }
    
    return baseline


def update_baseline_file(baseline_path: str, new_baseline: Dict[str, Any]):
    """
    Update baseline file with new data.
    
    Args:
        baseline_path: Path to baseline file
        new_baseline: New baseline dict
    """
    baseline_file = Path(baseline_path)
    baseline_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Update timestamp
    from datetime import datetime, timezone
    new_baseline["_timestamp_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # Write with sorted keys and indentation
    with open(baseline_file, "w") as f:
        json.dump(new_baseline, f, indent=2, sort_keys=True)
    
    print(f"[BASELINE] Updated: {baseline_file}")
    print(f"[BASELINE] Stages: {len(new_baseline['stages'])}")
    print(f"[BASELINE] Timestamp: {new_baseline['_timestamp_utc']}")


def compare_with_existing(baseline_path: str, new_baseline: Dict[str, Any]):
    """
    Compare new baseline with existing one and show diff.
    
    Args:
        baseline_path: Path to existing baseline file
        new_baseline: New baseline dict
    """
    baseline_file = Path(baseline_path)
    
    if not baseline_file.exists():
        print("[BASELINE] No existing baseline found (new file)")
        return
    
    with open(baseline_file, "r") as f:
        old_baseline = json.load(f)
    
    print("")
    print("=" * 60)
    print("BASELINE COMPARISON")
    print("=" * 60)
    print("")
    print("| Stage | Old p95 (ms) | New p95 (ms) | Diff (%) |")
    print("|-------|--------------|--------------|----------|")
    
    old_stages = old_baseline.get("stages", {})
    new_stages = new_baseline.get("stages", {})
    
    all_stages = set(old_stages.keys()) | set(new_stages.keys())
    
    for stage in sorted(all_stages):
        old_p95 = old_stages.get(stage, {}).get("p95_ms", 0.0)
        new_p95 = new_stages.get(stage, {}).get("p95_ms", 0.0)
        
        if old_p95 > 0:
            diff_pct = ((new_p95 - old_p95) / old_p95) * 100
            status = "✅" if diff_pct <= 3 else "⚠️"
        else:
            diff_pct = 0.0
            status = "➕"
        
        print(f"| {stage} | {old_p95:.2f} | {new_p95:.2f} | {diff_pct:+.2f}% {status} |")
    
    print("")


def main():
    parser = argparse.ArgumentParser(description="Update baseline from shadow mode profile")
    parser.add_argument(
        '--profile',
        default='artifacts/shadow/stage_profile_pipeline.json',
        help='Path to stage profile JSON'
    )
    parser.add_argument(
        '--baseline',
        default='artifacts/baseline/stage_budgets.json',
        help='Path to baseline file to update'
    )
    parser.add_argument(
        '--no-update',
        action='store_true',
        help='Dry run - show comparison but don\'t update'
    )
    
    args = parser.parse_args()
    
    # Load profile
    print(f"[BASELINE] Loading profile: {args.profile}")
    profile = load_profile(args.profile)
    
    # Generate new baseline
    new_baseline = generate_baseline(profile)
    
    # Compare with existing
    compare_with_existing(args.baseline, new_baseline)
    
    # Update file (unless dry run)
    if args.no_update:
        print("[BASELINE] Dry run - not updating file")
    else:
        update_baseline_file(args.baseline, new_baseline)
        print("")
        print("✅ Baseline updated successfully")


if __name__ == '__main__':
    main()


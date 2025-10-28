#!/usr/bin/env python3
"""
Shadow Artifact Auditor

Analyzes shadow mode artifacts and generates comprehensive readiness report.
Uses same analysis framework as tools.soak.audit_artifacts.

Usage:
    python -m tools.shadow.audit_shadow_artifacts
    python -m tools.shadow.audit_shadow_artifacts --base artifacts/shadow/latest --fail-on-hold
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# Import robust KPI extraction from soak tools
try:
    from tools.soak.audit_artifacts import robust_kpi_extract, compute_stats, check_readiness
except ImportError:
    print("ERROR: Cannot import from tools.soak.audit_artifacts", file=sys.stderr)
    print("Make sure tools/soak/audit_artifacts.py exists", file=sys.stderr)
    sys.exit(1)


# Shadow-specific thresholds (slightly relaxed vs soak)
SHADOW_THRESHOLDS = {
    "maker_taker_ratio": (">=", 0.83),
    "net_bps": (">=", 2.5),  # Slightly lower than soak (2.9)
    "p95_latency_ms": ("<=", 350),  # Slightly higher than soak (330)
    "risk_ratio": ("<=", 0.40),
}


def audit_shadow_artifacts(base_dir: str = "artifacts/shadow/latest", min_windows: int = 48) -> dict:
    """
    Audit shadow artifacts and generate readiness report.
    
    Similar to audit_artifacts but adapted for shadow mode.
    
    Args:
        base_dir: Path to shadow artifacts directory
        min_windows: Minimum required iterations (default: 48)
    
    Returns:
        dict with readiness status and KPIs
    """
    base_path = Path(base_dir)
    
    print("=" * 80)
    print(f"SHADOW ARTIFACT AUDIT: {base_dir}")
    print(f"Min Windows Gate: {min_windows}")
    print("=" * 80)
    print()
    
    # Load ITER_SUMMARY files
    print("[1/4] Loading ITER_SUMMARY files...")
    iter_files = sorted(base_path.glob("ITER_SUMMARY_*.json"))
    
    if not iter_files:
        print(f"ERROR: No ITER_SUMMARY_*.json files found in {base_dir}")
        return {"readiness": {"pass": False, "failures": ["No ITER_SUMMARY files found"]}}
    
    print(f"✓ Found {len(iter_files)} iterations")
    
    # Min-windows gate
    if len(iter_files) < min_windows:
        print(f"❌ FAIL: Not enough windows ({len(iter_files)} < {min_windows})")
        return {
            "readiness": {
                "pass": False,
                "failures": [f"Insufficient windows: {len(iter_files)} < {min_windows} (required)"]
            }
        }
    
    # Schema validation
    print("  Validating schema...")
    try:
        import jsonschema
        schema_path = Path("schema/iter_summary.schema.json")
        if schema_path.exists():
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            
            for iter_file in iter_files:
                with open(iter_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                jsonschema.validate(instance=data, schema=schema)
            
            print("  ✓ Schema validation passed")
        else:
            print("  ⚠ Schema file not found, skipping validation")
    except ImportError:
        print("  ⚠ jsonschema not installed, skipping validation")
    except jsonschema.ValidationError as e:
        print(f"  ✗ Schema validation FAILED: {e.message}")
        print(f"    File: {e.instance}")
        return {"readiness": {"pass": False, "failures": [f"Schema validation failed: {e.message}"]}}
    except Exception as e:
        print(f"  ⚠ Schema validation error: {e}")
    
    # Load data
    iter_data = []
    for iter_file in iter_files:
        try:
            with open(iter_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            iter_idx = data.get("iteration", len(iter_data) + 1)
            kpi = robust_kpi_extract(data, iter_idx)
            iter_data.append(kpi)
        except Exception as e:
            print(f"  WARNING: Failed to load {iter_file.name}: {e}")
    
    if not iter_data:
        print("ERROR: No valid iteration data loaded")
        return {"readiness": {"pass": False, "failures": ["No valid iteration data"]}}
    
    print(f"✓ Loaded {len(iter_data)} iterations")
    print()
    
    # Load snapshot
    print("[2/4] Loading POST_SHADOW_SNAPSHOT...")
    snapshot_path = base_path / "reports" / "analysis" / "POST_SHADOW_SNAPSHOT.json"
    
    if snapshot_path.exists():
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            snapshot = json.load(f)
        snapshot_kpis = snapshot.get("snapshot_kpis", {})
        print("✓ Snapshot loaded")
    else:
        print("⚠ POST_SHADOW_SNAPSHOT.json not found, deriving from last-8 window")
        # Compute from last 8 iterations
        last_8 = iter_data[-8:] if len(iter_data) >= 8 else iter_data
        kpi_columns = ["maker_taker_ratio", "net_bps", "latency_p95_ms", "risk_ratio"]
        
        snapshot_kpis = {}
        for col in kpi_columns:
            values = [row[col] for row in last_8]
            stats = compute_stats(values)
            snapshot_kpis[col] = stats["median"]
            
            # Rename latency key
            if col == "latency_p95_ms":
                snapshot_kpis["p95_latency_ms"] = snapshot_kpis.pop(col)
    
    print()
    
    # Readiness check
    print("[3/4] Readiness Gate (shadow thresholds)...")
    all_pass, failures = check_readiness(snapshot_kpis, "last-8")
    
    # Override thresholds with shadow-specific ones
    all_pass_shadow = True
    failures_shadow = []
    
    for metric, (op, threshold) in SHADOW_THRESHOLDS.items():
        actual = snapshot_kpis.get(metric, float('nan'))
        
        if actual != actual:  # NaN check
            failures_shadow.append(f"{metric}: missing (expected {op} {threshold})")
            all_pass_shadow = False
            continue
        
        passed = False
        if op == ">=":
            passed = actual >= threshold
        elif op == "<=":
            passed = actual <= threshold
        
        if not passed:
            failures_shadow.append(f"{metric}: {actual:.3f} (expected {op} {threshold})")
            all_pass_shadow = False
    
    print(f"{'Metric':<20} {'Target':<15} {'Actual':>10} {'Status':>10}")
    print("-" * 60)
    for metric, (op, threshold) in SHADOW_THRESHOLDS.items():
        actual = snapshot_kpis.get(metric, float('nan'))
        target_str = f"{op} {threshold}"
        
        if actual != actual:
            status = "MISSING"
        else:
            passed = (actual >= threshold) if op == ">=" else (actual <= threshold)
            status = "✓ PASS" if passed else "✗ FAIL"
        
        print(f"{metric:<20} {target_str:<15} {actual:>10.3f} {status:>10}")
    
    print()
    if all_pass_shadow:
        print("✅ READINESS: OK (shadow thresholds)")
    else:
        print("❌ READINESS: HOLD (shadow thresholds)")
        for failure in failures_shadow:
            print(f"  - {failure}")
    print()
    
    # Generate summary
    print("[4/4] Generating audit summary...")
    
    out_dir = base_path / "reports" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    audit_summary = {
        "mode": "shadow",
        "timestamp": iter_data[-1].get("timestamp", "unknown"),
        "iterations": len(iter_data),
        "snapshot_kpis": snapshot_kpis,
        "readiness": {
            "pass": all_pass_shadow,
            "failures": failures_shadow,
        },
        "thresholds": SHADOW_THRESHOLDS,
    }
    
    summary_file = out_dir / "POST_SHADOW_AUDIT_SUMMARY.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(audit_summary, f, indent=2)
    
    print(f"✓ Saved: {summary_file}")
    print()
    
    # Final verdict
    verdict = "READINESS: OK" if all_pass_shadow else f"READINESS: HOLD ({len(failures_shadow)} KPI(s) failed)"
    print("=" * 80)
    print(f"🎯 FINAL VERDICT: {verdict}")
    print("=" * 80)
    
    return audit_summary


def main():
    parser = argparse.ArgumentParser(
        description="Audit shadow mode artifacts and generate readiness report"
    )
    parser.add_argument(
        "--base",
        default="artifacts/shadow/latest",
        help="Base directory for shadow artifacts (default: artifacts/shadow/latest)"
    )
    parser.add_argument(
        "--fail-on-hold",
        action="store_true",
        help="Exit with code 1 if readiness is HOLD (default: False)"
    )
    parser.add_argument(
        "--min_windows",
        type=int,
        default=48,
        help="Minimum required iterations (default: 48)"
    )
    
    args = parser.parse_args()
    
    try:
        result = audit_shadow_artifacts(args.base, min_windows=args.min_windows)
        readiness_pass = result.get("readiness", {}).get("pass", False)
        
        # Determine exit code
        exit_code = 0
        if args.fail_on_hold and not readiness_pass:
            exit_code = 1
        
        verdict = "OK" if readiness_pass else "HOLD"
        print(f"[EXIT] fail-on-hold: {args.fail_on_hold}, verdict: {verdict}, exit_code={exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


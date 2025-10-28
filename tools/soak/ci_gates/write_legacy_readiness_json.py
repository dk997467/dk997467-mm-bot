#!/usr/bin/env python3
"""
Legacy Readiness JSON Bridge.

Reads POST_SOAK_AUDIT_SUMMARY.json or POST_SOAK_SNAPSHOT.json
and writes legacy artifacts/reports/readiness.json for backward compatibility.

Usage:
    python -m tools.soak.ci_gates.write_legacy_readiness_json \
        --src artifacts/soak/latest \
        --out artifacts/reports
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def find_source_snapshot(src_dir: Path) -> Optional[Path]:
    """
    Find source snapshot file in priority order.
    
    Search order:
    1. {src_dir}/reports/analysis/POST_SOAK_AUDIT_SUMMARY.json
    2. {src_dir}/reports/analysis/POST_SOAK_SNAPSHOT.json
    3. {src_dir}/POST_SOAK_SNAPSHOT.json
    
    Returns:
        Path to source file if found, None otherwise
    """
    candidates = [
        src_dir / "reports" / "analysis" / "POST_SOAK_AUDIT_SUMMARY.json",
        src_dir / "reports" / "analysis" / "POST_SOAK_SNAPSHOT.json",
        src_dir / "POST_SOAK_SNAPSHOT.json",
    ]
    
    for candidate in candidates:
        if candidate.exists():
            return candidate
    
    return None


def extract_kpis_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Extract KPI metrics from POST_SOAK_SNAPSHOT.json.
    
    Handles multiple schema versions:
    - New: kpi_last_n.{metric}.median
    - Old: kpi_last_8.{metric}.median
    - Fallback: kpi_overall.{metric}.mean
    """
    kpis = {
        "maker_taker_ratio": None,
        "net_bps": None,
        "p95_latency_ms": None,
        "risk_ratio": None,
    }
    
    # Try new schema: kpi_last_n
    if "kpi_last_n" in snapshot:
        kpi_data = snapshot["kpi_last_n"]
        if "maker_taker_ratio" in kpi_data and "median" in kpi_data["maker_taker_ratio"]:
            kpis["maker_taker_ratio"] = kpi_data["maker_taker_ratio"]["median"]
        if "net_bps" in kpi_data and "median" in kpi_data["net_bps"]:
            kpis["net_bps"] = kpi_data["net_bps"]["median"]
        if "p95_latency_ms" in kpi_data and "max" in kpi_data["p95_latency_ms"]:
            kpis["p95_latency_ms"] = kpi_data["p95_latency_ms"]["max"]
        if "risk_ratio" in kpi_data and "median" in kpi_data["risk_ratio"]:
            kpis["risk_ratio"] = kpi_data["risk_ratio"]["median"]
    
    # Fallback: kpi_last_8 (old schema)
    elif "kpi_last_8" in snapshot:
        kpi_data = snapshot["kpi_last_8"]
        if "maker_taker_ratio" in kpi_data and "median" in kpi_data["maker_taker_ratio"]:
            kpis["maker_taker_ratio"] = kpi_data["maker_taker_ratio"]["median"]
        if "net_bps" in kpi_data and "median" in kpi_data["net_bps"]:
            kpis["net_bps"] = kpi_data["net_bps"]["median"]
        if "p95_latency_ms" in kpi_data and "max" in kpi_data["p95_latency_ms"]:
            kpis["p95_latency_ms"] = kpi_data["p95_latency_ms"]["max"]
        if "risk_ratio" in kpi_data and "median" in kpi_data["risk_ratio"]:
            kpis["risk_ratio"] = kpi_data["risk_ratio"]["median"]
    
    # Last fallback: kpi_overall.mean
    elif "kpi_overall" in snapshot:
        kpi_data = snapshot["kpi_overall"]
        if "maker_taker_ratio" in kpi_data and "mean" in kpi_data["maker_taker_ratio"]:
            kpis["maker_taker_ratio"] = kpi_data["maker_taker_ratio"]["mean"]
        if "net_bps" in kpi_data and "mean" in kpi_data["net_bps"]:
            kpis["net_bps"] = kpi_data["net_bps"]["mean"]
        if "p95_latency_ms" in kpi_data and "mean" in kpi_data["p95_latency_ms"]:
            kpis["p95_latency_ms"] = kpi_data["p95_latency_ms"]["mean"]
        if "risk_ratio" in kpi_data and "mean" in kpi_data["risk_ratio"]:
            kpis["risk_ratio"] = kpi_data["risk_ratio"]["mean"]
    
    return kpis


def extract_kpis_from_audit_summary(audit_summary: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Extract KPI metrics from POST_SOAK_AUDIT_SUMMARY.json.
    
    Schema: snapshot_kpis.{metric}
    """
    kpis = {
        "maker_taker_ratio": None,
        "net_bps": None,
        "p95_latency_ms": None,
        "risk_ratio": None,
    }
    
    if "snapshot_kpis" in audit_summary:
        snapshot_kpis = audit_summary["snapshot_kpis"]
        if "maker_taker_ratio" in snapshot_kpis:
            kpis["maker_taker_ratio"] = snapshot_kpis["maker_taker_ratio"]
        if "net_bps" in snapshot_kpis:
            kpis["net_bps"] = snapshot_kpis["net_bps"]
        if "p95_latency_ms" in snapshot_kpis:
            kpis["p95_latency_ms"] = snapshot_kpis["p95_latency_ms"]
        if "risk_ratio" in snapshot_kpis:
            kpis["risk_ratio"] = snapshot_kpis["risk_ratio"]
    
    return kpis


def extract_failures_from_snapshot(snapshot: Dict[str, Any]) -> List[str]:
    """Extract failure reasons from snapshot."""
    failures = []
    
    # Check verdict field
    verdict = snapshot.get("verdict", "UNKNOWN")
    if verdict not in ("PASS", "OK"):
        failures.append(f"verdict={verdict}")
    
    # Check goals if available
    if "goals" in snapshot:
        goals = snapshot["goals"]
        for key, goal in goals.items():
            if isinstance(goal, dict):
                status = goal.get("status")
                if status == "FAIL":
                    failures.append(f"{key}_FAIL")
    
    return failures


def extract_failures_from_audit_summary(audit_summary: Dict[str, Any]) -> List[str]:
    """Extract failure reasons from audit summary."""
    failures = []
    
    # Check readiness.failures
    if "readiness" in audit_summary and "failures" in audit_summary["readiness"]:
        failures.extend(audit_summary["readiness"]["failures"])
    
    # Check readiness.pass
    if "readiness" in audit_summary:
        readiness_pass = audit_summary["readiness"].get("pass", True)
        if not readiness_pass and not failures:
            failures.append("readiness_hold")
    
    return failures


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Write legacy readiness.json for backward compatibility"
    )
    parser.add_argument(
        "--src",
        type=str,
        required=True,
        help="Source directory containing POST_SOAK_*.json files"
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output directory for readiness.json"
    )
    
    args = parser.parse_args()
    
    src_dir = Path(args.src).resolve()
    out_dir = Path(args.out).resolve()
    
    print("=" * 80)
    print("LEGACY READINESS.JSON BRIDGE")
    print("=" * 80)
    print(f"Source: {src_dir}")
    print(f"Output: {out_dir}")
    print()
    
    # Find source snapshot
    source_path = find_source_snapshot(src_dir)
    
    if source_path is None:
        print("[ERROR] No source snapshot found")
        print("  Searched for:")
        print(f"    - {src_dir}/reports/analysis/POST_SOAK_AUDIT_SUMMARY.json")
        print(f"    - {src_dir}/reports/analysis/POST_SOAK_SNAPSHOT.json")
        print(f"    - {src_dir}/POST_SOAK_SNAPSHOT.json")
        print()
        print("[FALLBACK] Writing minimal readiness.json with HOLD status")
        
        # Write minimal fallback
        out_dir.mkdir(parents=True, exist_ok=True)
        fallback_data = {
            "status": "hold",
            "maker_taker_ratio": None,
            "net_bps": None,
            "p95_latency_ms": None,
            "risk_ratio": None,
            "failures": ["snapshot_missing"]
        }
        
        output_path = out_dir / "readiness.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(fallback_data, f, indent=2)
        
        print(f"[OK] Wrote fallback: {output_path}")
        return 0
    
    print(f"[OK] Found source: {source_path}")
    print()
    
    # Load source
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            source_data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load {source_path}: {e}")
        return 1
    
    # Extract KPIs and failures based on source type
    if "POST_SOAK_AUDIT_SUMMARY" in source_path.name:
        print("[INFO] Source type: POST_SOAK_AUDIT_SUMMARY.json")
        kpis = extract_kpis_from_audit_summary(source_data)
        failures = extract_failures_from_audit_summary(source_data)
        
        # Determine status from readiness.pass
        readiness_pass = source_data.get("readiness", {}).get("pass", False)
        status = "ok" if readiness_pass else "hold"
    else:
        print("[INFO] Source type: POST_SOAK_SNAPSHOT.json")
        kpis = extract_kpis_from_snapshot(source_data)
        failures = extract_failures_from_snapshot(source_data)
        
        # Determine status from verdict
        verdict = source_data.get("verdict", "UNKNOWN")
        status = "ok" if verdict == "PASS" else "hold"
    
    # Build legacy readiness.json
    readiness = {
        "status": status,
        "maker_taker_ratio": kpis["maker_taker_ratio"],
        "net_bps": kpis["net_bps"],
        "p95_latency_ms": kpis["p95_latency_ms"],
        "risk_ratio": kpis["risk_ratio"],
        "failures": failures
    }
    
    # Write output
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "readiness.json"
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(readiness, f, indent=2)
    
    print("[OK] Legacy readiness.json written:")
    print(f"  Path: {output_path}")
    print(f"  Status: {status}")
    print(f"  maker_taker_ratio: {kpis['maker_taker_ratio']}")
    print(f"  net_bps: {kpis['net_bps']}")
    print(f"  p95_latency_ms: {kpis['p95_latency_ms']}")
    print(f"  risk_ratio: {kpis['risk_ratio']}")
    print(f"  failures: {failures if failures else '(none)'}")
    print()
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())


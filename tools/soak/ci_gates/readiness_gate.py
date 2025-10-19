#!/usr/bin/env python3
"""
Readiness Gate for CI/CD pipelines.

Validates KPI metrics from POST_SOAK_SNAPSHOT.json against configured thresholds.
Returns exit code 0 for PASS, 1 for FAIL.

Supports READINESS_OVERRIDE=1 environment variable for forced PASS (testing/debugging).

Usage:
    python -m tools.soak.ci_gates.readiness_gate \
        --path artifacts/soak/latest \
        --min_maker_taker 0.83 \
        --min_edge 2.9 \
        --max_latency 330 \
        --max_risk 0.40
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def find_snapshot(base_path: Path) -> Optional[Path]:
    """
    Find POST_SOAK_SNAPSHOT.json in one of the expected locations.
    
    Search order:
    1. {base_path}/reports/analysis/POST_SOAK_SNAPSHOT.json
    2. {base_path}/POST_SOAK_SNAPSHOT.json
    
    Returns:
        Path to snapshot file if found, None otherwise
    """
    candidates = [
        base_path / "reports" / "analysis" / "POST_SOAK_SNAPSHOT.json",
        base_path / "POST_SOAK_SNAPSHOT.json",
    ]
    
    for candidate in candidates:
        if candidate.exists():
            return candidate
    
    return None


def extract_kpis(snapshot: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Extract KPI values from POST_SOAK_SNAPSHOT.json.
    
    Tries multiple possible structures:
    - snapshot["kpi_last_n"][metric]["mean"|"median"]
    - snapshot["last8"][metric]
    - snapshot["metrics"][metric]
    
    Returns:
        Dictionary with extracted values (None if not found)
    """
    kpis = {
        "maker_taker_ratio": None,
        "net_bps": None,
        "p95_latency_ms": None,
        "risk_ratio": None,
    }
    
    # Try structure 1: kpi_last_n (from build_reports)
    if "kpi_last_n" in snapshot:
        kpi_block = snapshot["kpi_last_n"]
        
        # maker_taker_ratio: use mean
        if "maker_taker_ratio" in kpi_block:
            mt = kpi_block["maker_taker_ratio"]
            kpis["maker_taker_ratio"] = mt.get("mean") or mt.get("median")
        
        # net_bps: use mean
        if "net_bps" in kpi_block:
            nb = kpi_block["net_bps"]
            kpis["net_bps"] = nb.get("mean") or nb.get("median")
        
        # p95_latency_ms: use max (worst case)
        if "p95_latency_ms" in kpi_block:
            p95 = kpi_block["p95_latency_ms"]
            kpis["p95_latency_ms"] = p95.get("max") or p95.get("mean")
        
        # risk_ratio: use median
        if "risk_ratio" in kpi_block:
            rr = kpi_block["risk_ratio"]
            kpis["risk_ratio"] = rr.get("median") or rr.get("mean")
    
    # Try structure 2: last8 (flat structure)
    elif "last8" in snapshot:
        last8 = snapshot["last8"]
        for key in kpis.keys():
            if key in last8:
                kpis[key] = last8[key]
    
    # Try structure 3: metrics (flat structure)
    elif "metrics" in snapshot:
        metrics = snapshot["metrics"]
        for key in kpis.keys():
            if key in metrics:
                kpis[key] = metrics[key]
    
    return kpis


def check_thresholds(
    kpis: Dict[str, Optional[float]],
    min_maker_taker: float,
    min_edge: float,
    max_latency: float,
    max_risk: float,
) -> Tuple[bool, Dict[str, bool]]:
    """
    Check KPIs against thresholds.
    
    Returns:
        (all_pass: bool, results: Dict[str, bool])
    """
    results = {}
    
    # maker_taker_ratio: >= threshold
    mt = kpis.get("maker_taker_ratio")
    if mt is not None:
        results["maker_taker"] = mt >= min_maker_taker
    else:
        results["maker_taker"] = False
    
    # net_bps (edge): >= threshold
    nb = kpis.get("net_bps")
    if nb is not None:
        results["net_bps"] = nb >= min_edge
    else:
        results["net_bps"] = False
    
    # p95_latency_ms: <= threshold
    p95 = kpis.get("p95_latency_ms")
    if p95 is not None:
        results["p95_latency"] = p95 <= max_latency
    else:
        results["p95_latency"] = False
    
    # risk_ratio: <= threshold
    rr = kpis.get("risk_ratio")
    if rr is not None:
        results["risk_ratio"] = rr <= max_risk
    else:
        results["risk_ratio"] = False
    
    all_pass = all(results.values())
    return all_pass, results


def print_summary(
    kpis: Dict[str, Optional[float]],
    results: Dict[str, bool],
    min_maker_taker: float,
    min_edge: float,
    max_latency: float,
    max_risk: float,
    verdict: str,
    override: bool = False,
):
    """Print readiness gate summary."""
    print("================================================")
    print("READINESS GATE")
    print("================================================")
    
    if override:
        print("Override: TRUE (forcing PASS)")
        print()
    
    # maker/taker
    mt = kpis.get("maker_taker_ratio")
    mt_status = "OK" if results.get("maker_taker", False) else "FAIL"
    mt_value = f"{mt:.3f}" if mt is not None else "N/A"
    print(f"  maker/taker: {mt_value} (>= {min_maker_taker:.2f}) -> {mt_status}")
    
    # net_bps (edge)
    nb = kpis.get("net_bps")
    nb_status = "OK" if results.get("net_bps", False) else "FAIL"
    nb_value = f"{nb:.2f}" if nb is not None else "N/A"
    print(f"  net_bps:     {nb_value} (>= {min_edge:.2f}) -> {nb_status}")
    
    # p95_latency
    p95 = kpis.get("p95_latency_ms")
    p95_status = "OK" if results.get("p95_latency", False) else "FAIL"
    p95_value = f"{p95:.0f}ms" if p95 is not None else "N/A"
    print(f"  p95_latency: {p95_value} (<= {max_latency:.0f}ms) -> {p95_status}")
    
    # risk_ratio
    rr = kpis.get("risk_ratio")
    rr_status = "OK" if results.get("risk_ratio", False) else "FAIL"
    rr_value = f"{rr:.3f}" if rr is not None else "N/A"
    print(f"  risk_ratio:  {rr_value} (<= {max_risk:.2f}) -> {rr_status}")
    
    print()
    print(f"Verdict: {verdict}")
    print("================================================")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Readiness Gate: Validate KPI metrics from soak test artifacts"
    )
    parser.add_argument(
        "--path",
        type=str,
        default="artifacts/soak/latest",
        help="Path to soak artifacts directory (default: artifacts/soak/latest)",
    )
    parser.add_argument(
        "--min_maker_taker",
        type=float,
        default=0.83,
        help="Minimum maker/taker ratio (default: 0.83)",
    )
    parser.add_argument(
        "--min_edge",
        type=float,
        default=2.9,
        help="Minimum net_bps (edge) (default: 2.9)",
    )
    parser.add_argument(
        "--max_latency",
        type=float,
        default=330.0,
        help="Maximum p95 latency in ms (default: 330)",
    )
    parser.add_argument(
        "--max_risk",
        type=float,
        default=0.40,
        help="Maximum risk ratio (default: 0.40)",
    )
    
    args = parser.parse_args()
    
    # Check for override
    override = os.environ.get("READINESS_OVERRIDE", "") == "1"
    
    # Find snapshot
    base_path = Path(args.path)
    snapshot_path = find_snapshot(base_path)
    
    if snapshot_path is None:
        print("================================================")
        print("READINESS GATE - SNAPSHOT NOT FOUND")
        print("================================================")
        print(f"Error: POST_SOAK_SNAPSHOT.json not found in:")
        print(f"  - {base_path / 'reports' / 'analysis' / 'POST_SOAK_SNAPSHOT.json'}")
        print(f"  - {base_path / 'POST_SOAK_SNAPSHOT.json'}")
        print()
        print("Verdict: FAIL (snapshot missing)")
        print("================================================")
        
        if override:
            print("Override: TRUE (forcing PASS despite missing snapshot)")
            return 0
        return 1
    
    # Load snapshot
    try:
        with open(snapshot_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
    except Exception as e:
        print("================================================")
        print("READINESS GATE - SNAPSHOT READ ERROR")
        print("================================================")
        print(f"Error reading {snapshot_path}: {e}")
        print()
        print("Verdict: FAIL (read error)")
        print("================================================")
        
        if override:
            print("Override: TRUE (forcing PASS despite read error)")
            return 0
        return 1
    
    # Extract KPIs
    kpis = extract_kpis(snapshot)
    
    # Debug: Log found structure
    print(f"[DEBUG] Loaded snapshot from: {snapshot_path}")
    print(f"[DEBUG] Snapshot keys: {list(snapshot.keys())}")
    print(f"[DEBUG] Extracted KPIs: {kpis}")
    print()
    
    # Check if any KPI is missing
    missing = [k for k, v in kpis.items() if v is None]
    if missing and not override:
        print("================================================")
        print("READINESS GATE - MISSING KPIs")
        print("================================================")
        print(f"Error: Could not extract KPIs: {', '.join(missing)}")
        print(f"Available snapshot keys: {list(snapshot.keys())}")
        print()
        print("Verdict: FAIL (missing metrics)")
        print("================================================")
        return 1
    
    # Check thresholds
    all_pass, results = check_thresholds(
        kpis,
        args.min_maker_taker,
        args.min_edge,
        args.max_latency,
        args.max_risk,
    )
    
    # Determine verdict
    if override:
        verdict = "PASS (override)"
        exit_code = 0
    elif all_pass:
        verdict = "PASS"
        exit_code = 0
    else:
        verdict = "FAIL"
        exit_code = 1
    
    # Print summary
    print_summary(
        kpis,
        results,
        args.min_maker_taker,
        args.min_edge,
        args.max_latency,
        args.max_risk,
        verdict,
        override=override,
    )
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())


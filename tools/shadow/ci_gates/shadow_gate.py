#!/usr/bin/env python3
"""
Shadow Mode CI Gate

Validates shadow mode KPIs against thresholds in CI/CD.
Fails with exit 1 if any KPI below thresholds.

Usage:
    python -m tools.shadow.ci_gates.shadow_gate --path artifacts/shadow/latest
    python -m tools.shadow.ci_gates.shadow_gate --path artifacts/shadow/latest \\
        --min_edge 2.5 --min_maker_taker 0.83 --max_risk 0.40 --max_latency 350
"""

import argparse
import json
import os
import sys
from pathlib import Path


def find_snapshot(base_path: Path):
    """Find POST_SHADOW_SNAPSHOT.json or POST_SHADOW_AUDIT_SUMMARY.json."""
    candidates = [
        base_path / "reports/analysis/POST_SHADOW_AUDIT_SUMMARY.json",
        base_path / "reports/analysis/POST_SHADOW_SNAPSHOT.json",
    ]
    
    for p in candidates:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f), str(p)
    
    return None, None


def extract_kpis(snap: dict) -> dict:
    """Extract KPIs from shadow snapshot."""
    # Try different structures
    kpi_last_n = snap.get("kpi_last_n", {})
    snapshot_kpis = snap.get("snapshot_kpis", {})
    
    # Prefer snapshot_kpis if present
    if snapshot_kpis:
        return {
            "maker_taker_ratio": float(snapshot_kpis.get("maker_taker_ratio", float('nan'))),
            "net_bps": float(snapshot_kpis.get("net_bps", float('nan'))),
            "p95_latency_ms": float(snapshot_kpis.get("p95_latency_ms", float('nan'))),
            "risk_ratio": float(snapshot_kpis.get("risk_ratio", float('nan'))),
        }
    
    # Fallback: extract from kpi_last_n
    return {
        "maker_taker_ratio": float(kpi_last_n.get("maker_taker_ratio", {}).get("median", float('nan'))),
        "net_bps": float(kpi_last_n.get("net_bps", {}).get("median", float('nan'))),
        "p95_latency_ms": float(kpi_last_n.get("p95_latency_ms", {}).get("median", float('nan'))),
        "risk_ratio": float(kpi_last_n.get("risk_ratio", {}).get("median", float('nan'))),
    }


def main():
    ap = argparse.ArgumentParser(description="Shadow Mode CI Gate")
    ap.add_argument("--path", default="artifacts/shadow/latest", help="Path to shadow artifacts")
    ap.add_argument("--min_maker_taker", type=float, default=0.83, help="Min maker/taker ratio")
    ap.add_argument("--min_edge", type=float, default=2.5, help="Min net_bps")
    ap.add_argument("--max_latency", type=float, default=350, help="Max p95 latency (ms)")
    ap.add_argument("--max_risk", type=float, default=0.40, help="Max risk ratio")
    args = ap.parse_args()
    
    # Check for override
    override = os.getenv("SHADOW_OVERRIDE") == "1"
    
    # Find snapshot
    snap, used = find_snapshot(Path(args.path))
    if snap is None:
        print(f"Shadow Gate: snapshot not found under {args.path}")
        if override:
            print("Override: TRUE (forcing PASS)")
            sys.exit(0)
        sys.exit(1)
    
    # Extract KPIs
    k = extract_kpis(snap)
    
    print("Shadow Gate (source:", used, ")")
    
    # Validate
    ok_mt = k["maker_taker_ratio"] >= args.min_maker_taker
    ok_edge = k["net_bps"] >= args.min_edge
    ok_lat = k["p95_latency_ms"] <= args.max_latency
    ok_risk = k["risk_ratio"] <= args.max_risk
    
    print(f"  maker/taker: {k['maker_taker_ratio']:.3f} (>= {args.min_maker_taker}) -> {'OK' if ok_mt else 'FAIL'}")
    print(f"  net_bps:     {k['net_bps']:.2f} (>= {args.min_edge}) -> {'OK' if ok_edge else 'FAIL'}")
    print(f"  p95_latency: {k['p95_latency_ms']:.0f}ms (<= {args.max_latency}) -> {'OK' if ok_lat else 'FAIL'}")
    print(f"  risk_ratio:  {k['risk_ratio']:.3f} (<= {args.max_risk}) -> {'OK' if ok_risk else 'FAIL'}")
    
    if override:
        print("Override: TRUE (forcing PASS)")
        sys.exit(0)
    
    verdict = ok_mt and ok_edge and ok_lat and ok_risk
    print("Verdict:", "PASS" if verdict else "FAIL")
    sys.exit(0 if verdict else 1)


if __name__ == "__main__":
    main()


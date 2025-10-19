#!/usr/bin/env python3
"""
Compare two soak runs (A vs B) by last-8 snapshot KPIs.

Usage:
    python -m tools.soak.compare_runs --a artifacts/soak/run_A --b artifacts/soak/latest
"""

import argparse
import json
import pathlib
import sys


def load_snapshot(base):
    """Load snapshot KPIs from POST_SOAK_AUDIT_SUMMARY.json."""
    p = pathlib.Path(base) / "reports/analysis/POST_SOAK_AUDIT_SUMMARY.json"
    if not p.exists():
        raise FileNotFoundError(f"Missing summary: {p}")
    j = json.loads(p.read_text())
    return j["snapshot_kpis"]


def main():
    ap = argparse.ArgumentParser(description="Compare two soak runs by KPIs")
    ap.add_argument("--a", required=True, help="Base dir for run A")
    ap.add_argument("--b", required=True, help="Base dir for run B")
    args = ap.parse_args()
    
    try:
        a, b = load_snapshot(args.a), load_snapshot(args.b)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("\nMake sure both runs have been analyzed with:", file=sys.stderr)
        print("  python -m tools.soak.audit_artifacts --base <dir>", file=sys.stderr)
        sys.exit(1)
    
    keys = ["maker_taker_ratio", "net_bps", "p95_latency_ms", "risk_ratio"]
    
    print("KPI,A,B,B-A (note: for latency smaller is better)")
    for k in keys:
        av, bv = a.get(k), b.get(k)
        if av is None or bv is None:
            delta_str = "nan"
        else:
            delta = bv - av
            delta_str = f"{delta:.3f}"
        
        av_str = f"{av:.3f}" if av is not None else "nan"
        bv_str = f"{bv:.3f}" if bv is not None else "nan"
        
        print(f"{k},{av_str},{bv_str},{delta_str}")


if __name__ == "__main__":
    main()


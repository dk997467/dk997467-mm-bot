#!/usr/bin/env python3
"""
Shadow Reports Builder

Generates POST_SHADOW_SNAPSHOT.json and summary reports from shadow run artifacts.

Usage:
    python -m tools.shadow.build_shadow_reports
    python -m tools.shadow.build_shadow_reports --src artifacts/shadow/latest --last-n 8
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')


def load_iter_summaries(base_dir: Path) -> List[Dict]:
    """Load all ITER_SUMMARY_*.json files."""
    summaries = []
    for iter_file in sorted(base_dir.glob("ITER_SUMMARY_*.json")):
        with open(iter_file, 'r', encoding='utf-8') as f:
            summaries.append(json.load(f))
    return summaries


def compute_snapshot(summaries: List[Dict], last_n: int) -> Dict:
    """
    Compute POST_SHADOW_SNAPSHOT from last N iterations.
    
    Returns snapshot with KPI aggregates (same schema as POST_SOAK_SNAPSHOT).
    """
    if not summaries:
        return {}
    
    # Take last N iterations
    relevant = summaries[-last_n:] if len(summaries) >= last_n else summaries
    
    # Extract KPIs
    maker_taker_ratios = [s["summary"]["maker_taker_ratio"] for s in relevant]
    net_bps_values = [s["summary"]["net_bps"] for s in relevant]
    latencies = [s["summary"]["p95_latency_ms"] for s in relevant]
    risks = [s["summary"]["risk_ratio"] for s in relevant]
    
    # Compute medians
    def median(values):
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        return sorted_vals[n // 2] if n > 0 else 0.0
    
    snapshot = {
        "mode": "shadow",
        "total_iterations": len(summaries),
        "window_size": len(relevant),
        "kpi_last_n": {
            "maker_taker_ratio": {
                "median": round(median(maker_taker_ratios), 3),
                "min": round(min(maker_taker_ratios), 3),
                "max": round(max(maker_taker_ratios), 3),
            },
            "net_bps": {
                "median": round(median(net_bps_values), 2),
                "min": round(min(net_bps_values), 2),
                "max": round(max(net_bps_values), 2),
            },
            "p95_latency_ms": {
                "median": round(median(latencies), 1),
                "min": round(min(latencies), 1),
                "max": round(max(latencies), 1),
            },
            "risk_ratio": {
                "median": round(median(risks), 3),
                "min": round(min(risks), 3),
                "max": round(max(risks), 3),
            },
        },
        "snapshot_kpis": {
            "maker_taker_ratio": round(median(maker_taker_ratios), 3),
            "net_bps": round(median(net_bps_values), 2),
            "p95_latency_ms": round(median(latencies), 1),
            "risk_ratio": round(median(risks), 3),
        },
    }
    
    return snapshot


def main():
    parser = argparse.ArgumentParser(
        description="Build shadow mode reports and snapshot"
    )
    parser.add_argument(
        "--src",
        default="artifacts/shadow/latest",
        help="Source directory with ITER_SUMMARY files (default: artifacts/shadow/latest)"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (default: <src>/reports/analysis)"
    )
    parser.add_argument(
        "--last-n",
        type=int,
        default=8,
        help="Use last N iterations for snapshot (default: 8)"
    )
    
    args = parser.parse_args()
    
    base_dir = Path(args.src)
    out_dir = Path(args.out) if args.out else base_dir / "reports" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 80)
    print("SHADOW REPORTS BUILDER")
    print("=" * 80)
    print(f"Source: {base_dir}")
    print(f"Output: {out_dir}")
    print(f"Window: last-{args.last_n}")
    print()
    
    # Load summaries
    print("[1/2] Loading ITER_SUMMARY files...")
    summaries = load_iter_summaries(base_dir)
    
    if not summaries:
        print("ERROR: No ITER_SUMMARY_*.json files found")
        return 1
    
    print(f"✓ Loaded {len(summaries)} iterations")
    print()
    
    # Compute snapshot
    print(f"[2/2] Computing snapshot (last-{args.last_n})...")
    snapshot = compute_snapshot(summaries, args.last_n)
    
    # Write snapshot
    snapshot_file = out_dir / "POST_SHADOW_SNAPSHOT.json"
    with open(snapshot_file, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, indent=2)
    
    print(f"✓ Saved: {snapshot_file}")
    print()
    
    # Print KPIs
    print("=" * 80)
    print("SHADOW SNAPSHOT KPIs (last-{})".format(args.last_n))
    print("=" * 80)
    
    kpis = snapshot["snapshot_kpis"]
    print(f"  maker_taker_ratio: {kpis['maker_taker_ratio']:.3f}")
    print(f"  net_bps:           {kpis['net_bps']:.2f}")
    print(f"  p95_latency_ms:    {kpis['p95_latency_ms']:.0f}")
    print(f"  risk_ratio:        {kpis['risk_ratio']:.3f}")
    print()
    print("=" * 80)
    print("SHADOW REPORTS COMPLETE")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    exit(main())


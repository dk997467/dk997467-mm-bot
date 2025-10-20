#!/usr/bin/env python3
"""
Write readiness.json from ITER_SUMMARY files.

Simple KPI aggregator that reads iteration summaries and writes readiness status.

Usage:
    python -m tools.soak.write_readiness \
        --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" \
        --out "artifacts/reports/readiness.json" \
        --min_maker_taker 0.83 --min_edge 2.9 --max_latency 330 --max_risk 0.40
"""

import argparse
import glob
import json
import pathlib
import statistics
import sys


def main():
    ap = argparse.ArgumentParser(description="Write readiness.json from ITER_SUMMARY files")
    ap.add_argument("--iter-glob", default="artifacts/soak/latest/ITER_SUMMARY_*.json",
                    help="Glob pattern for ITER_SUMMARY files")
    ap.add_argument("--out", default="artifacts/reports/readiness.json",
                    help="Output path for readiness.json")
    ap.add_argument("--min_maker_taker", type=float, default=0.83,
                    help="Minimum maker/taker ratio")
    ap.add_argument("--min_edge", type=float, default=2.9,
                    help="Minimum net_bps (edge)")
    ap.add_argument("--max_latency", type=float, default=330.0,
                    help="Maximum p95 latency in ms")
    ap.add_argument("--max_risk", type=float, default=0.40,
                    help="Maximum risk ratio")
    args = ap.parse_args()

    # Find and load iteration summaries
    files = sorted(glob.glob(args.iter_glob))
    
    if not files:
        print(f"[write_readiness] WARN: No files found matching {args.iter_glob}", file=sys.stderr)
        print("[write_readiness] Writing HOLD status (no data)", file=sys.stderr)
        mk = nb = rr = 0.0
        lt = 9999.0
    else:
        print(f"[write_readiness] Found {len(files)} iteration summaries", file=sys.stderr)
        data = []
        for f in files:
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data.append(json.load(fp))
            except Exception as e:
                print(f"[write_readiness] WARN: Failed to load {f}: {e}", file=sys.stderr)
        
        if not data:
            print("[write_readiness] ERROR: No valid data loaded", file=sys.stderr)
            mk = nb = rr = 0.0
            lt = 9999.0
        else:
            # Extract KPIs from iteration summaries
            # Support both direct fields and nested kpi object
            def get_kpi(item, key):
                if key in item:
                    return item[key]
                if "kpi" in item and key in item["kpi"]:
                    return item["kpi"][key]
                return None
            
            mk_values = [get_kpi(x, "maker_taker_ratio") for x in data]
            nb_values = [get_kpi(x, "net_bps") for x in data]
            lt_values = [get_kpi(x, "p95_latency_ms") for x in data]
            rr_values = [get_kpi(x, "risk_ratio") for x in data]
            
            # Filter out None values
            mk_values = [v for v in mk_values if v is not None]
            nb_values = [v for v in nb_values if v is not None]
            lt_values = [v for v in lt_values if v is not None]
            rr_values = [v for v in rr_values if v is not None]
            
            mk = statistics.mean(mk_values) if mk_values else 0.0
            nb = statistics.mean(nb_values) if nb_values else 0.0
            lt = statistics.mean(lt_values) if lt_values else 9999.0
            rr = statistics.mean(rr_values) if rr_values else 0.0
    
    # Check thresholds
    status = "OK" if (
        mk >= args.min_maker_taker and
        nb >= args.min_edge and
        lt <= args.max_latency and
        rr <= args.max_risk
    ) else "HOLD"

    # Write output
    outp = pathlib.Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    
    readiness = {
        "status": status,
        "maker_taker": mk,
        "net_bps": nb,
        "p95_latency_ms": lt,
        "risk_ratio": rr
    }
    
    outp.write_text(json.dumps(readiness, indent=2), encoding="utf-8")
    
    print(f"[write_readiness] status={status} → {outp}")
    print(f"[write_readiness] maker_taker={mk:.3f} (>= {args.min_maker_taker})")
    print(f"[write_readiness] net_bps={nb:.2f} (>= {args.min_edge})")
    print(f"[write_readiness] p95_latency_ms={lt:.0f} (<= {args.max_latency})")
    print(f"[write_readiness] risk_ratio={rr:.3f} (<= {args.max_risk})")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())


#!/usr/bin/env python3
"""Regional canary comparison."""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--regions", required=True)
    p.add_argument("--in", dest="input_file", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    
    # Load input JSONL
    metrics_by_region = {}
    with open(args.input_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            region = data.get("region", "unknown")
            if region not in metrics_by_region:
                metrics_by_region[region] = []
            metrics_by_region[region].append(data)
    
    # Aggregate per region
    by_region = {}
    for region, metrics_list in metrics_by_region.items():
        by_region[region] = _aggregate_metrics(metrics_list)
    
    # Determine winner
    winner, reason = _select_winner(by_region)
    
    # Build output
    # Deterministic time for tests
    import os
    if os.environ.get('MM_FREEZE_UTC') == '1':
        utc_iso = "1970-01-01T00:00:00Z"
    else:
        utc_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    report = {
        "by_region": by_region,
        "winner": winner,
        "reason": reason,
        "runtime": {
            "utc": utc_iso,
            "version": "0.1.0"
        }
    }
    
    # Write output
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write('\n')
    
    return 0


def _aggregate_metrics(metrics_list):
    """Aggregate metrics for a region."""
    if not metrics_list:
        return {
            "net_bps": 0.0,
            "order_age_p95_ms": 0.0,
            "taker_share_pct": 0.0,
            "count": 0
        }
    
    return {
        "net_bps": sum(m.get("net_bps", 0.0) for m in metrics_list) / len(metrics_list),
        "order_age_p95_ms": sum(m.get("order_age_p95_ms", 0.0) for m in metrics_list) / len(metrics_list),
        "taker_share_pct": sum(m.get("taker_share_pct", 0.0) for m in metrics_list) / len(metrics_list),
        "count": len(metrics_list)
    }


def _select_winner(by_region):
    """Select winner: best net_bps, tie -> lowest latency."""
    if not by_region:
        return "unknown", "no_data"
    
    # Sort by net_bps desc, then order_age_p95_ms asc
    sorted_regions = sorted(
        by_region.items(),
        key=lambda x: (-x[1].get("net_bps", 0.0), x[1].get("order_age_p95_ms", 999999.0))
    )
    
    winner = sorted_regions[0][0]
    return winner, "best_net_bps_tie_latency"


if __name__ == "__main__":
    sys.exit(main())

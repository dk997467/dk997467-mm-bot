#!/usr/bin/env python3
"""Regional canary comparison."""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--regions", required=True)
    p.add_argument("--in", dest="input_file", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    
    # Load input JSONL and group by region and window
    regions_data = defaultdict(list)
    windows_data = defaultdict(list)
    
    with open(args.input_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            region = data.get("region", "unknown")
            window = data.get("window", "unknown")
            regions_data[region].append(data)
            windows_data[window].append(data)
    
    # Aggregate per region
    regions = {}
    for region, metrics in regions_data.items():
        regions[region] = {
            "fill_rate": sum(m.get("fill_rate", 0) for m in metrics) / len(metrics),
            "net_bps": sum(m.get("net_bps", 0) for m in metrics) / len(metrics),
            "order_age_p95_ms": sum(m.get("order_age_p95_ms", 0) for m in metrics) / len(metrics),
            "taker_share_pct": sum(m.get("taker_share_pct", 0) for m in metrics) / len(metrics),
        }
    
    # Aggregate per window
    windows = {}
    for window, metrics in windows_data.items():
        windows[window] = {
            "fill_rate": sum(m.get("fill_rate", 0) for m in metrics) / len(metrics),
            "net_bps": sum(m.get("net_bps", 0) for m in metrics) / len(metrics),
            "order_age_p95_ms": sum(m.get("order_age_p95_ms", 0) for m in metrics) / len(metrics),
            "taker_share_pct": sum(m.get("taker_share_pct", 0) for m in metrics) / len(metrics),
        }
    
    # Find best region+window combination (highest net_bps)
    best_region = max(regions.items(), key=lambda x: x[1]["net_bps"])[0]
    best_window = max(windows.items(), key=lambda x: x[1]["net_bps"])[0]
    
    # Build output matching golden format
    import os
    if os.environ.get('MM_FREEZE_UTC') == '1':
        utc_iso = "1970-01-01T00:00:00Z"
    else:
        utc_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    report = {
        "regions": regions,
        "runtime": {
            "utc": utc_iso,
            "version": "0.1.0"
        },
        "windows": windows,
        "winner": {
            "region": best_region,
            "window": best_window
        }
    }
    
    # Write output
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        json.dump(report, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write('\n')
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

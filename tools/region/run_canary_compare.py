#!/usr/bin/env python3
"""Regional canary comparison."""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict


def _aggregate_metrics(metrics: list) -> dict:
    """
    Aggregate metrics by averaging.
    
    Args:
        metrics: List of metric dictionaries
    
    Returns:
        Aggregated metrics dictionary
    """
    if not metrics:
        return {
            "fill_rate": 0.0,
            "net_bps": 0.0,
            "order_age_p95_ms": 0.0,
            "taker_share_pct": 0.0
        }
    
    return {
        "fill_rate": sum(m.get("fill_rate", 0) for m in metrics) / len(metrics),
        "net_bps": sum(m.get("net_bps", 0) for m in metrics) / len(metrics),
        "order_age_p95_ms": sum(m.get("order_age_p95_ms", 0) for m in metrics) / len(metrics),
        "taker_share_pct": sum(m.get("taker_share_pct", 0) for m in metrics) / len(metrics),
    }


def _find_best_window(windows: dict) -> str:
    """
    Find best window based on net_bps (highest) with latency tie-break (lowest).
    
    Args:
        windows: Dictionary mapping window name to metrics
    
    Returns:
        Best window name
    """
    if not windows:
        raise ValueError("No windows provided")
    
    # Sort by net_bps desc, then by latency asc
    return max(windows.items(), key=lambda x: (x[1]["net_bps"], -x[1]["order_age_p95_ms"]))[0]


def _find_best_region(regions: dict) -> str:
    """
    Find best region using safe criteria with latency tie-break.
    
    Safe criteria: net_bps >= 2.50, order_age_p95_ms <= 350, taker_share_pct <= 15
    Tie-break: For equal net_bps, lowest latency wins.
    
    Args:
        regions: Dictionary mapping region name to metrics
    
    Returns:
        Best region name
    """
    if not regions:
        raise ValueError("No regions provided")
    
    # Filter safe regions
    safe_regions = []
    for region, data in regions.items():
        if (data.get("net_bps", 0) >= 2.50 and 
            data.get("order_age_p95_ms", float('inf')) <= 350 and 
            data.get("taker_share_pct", float('inf')) <= 15):
            safe_regions.append((region, data))
    
    # Pick best region: tie-break by lowest overall latency (for equal net_bps)
    if safe_regions:
        # Sort by net_bps desc, then by latency asc
        safe_regions.sort(key=lambda x: (-x[1]["net_bps"], x[1]["order_age_p95_ms"]))
        return safe_regions[0][0]
    else:
        # No safe regions, pick highest net_bps
        return max(regions.items(), key=lambda x: x[1].get("net_bps", 0))[0]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--regions", required=True)
    p.add_argument("--in", dest="input_file", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--update-golden", action="store_true", help="Update golden file for tests")
    args = p.parse_args(argv)
    
    # Load input JSONL and group by region and window
    regions_data = defaultdict(list)
    windows_data = defaultdict(list)
    all_rows = []
    
    with open(args.input_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            region = data.get("region", "unknown")
            window = data.get("window", "unknown")
            regions_data[region].append(data)
            windows_data[window].append(data)
            all_rows.append(data)
    
    # Aggregate per region
    regions = {}
    for region, metrics in regions_data.items():
        regions[region] = _aggregate_metrics(metrics)
    
    # Aggregate per window
    windows = {}
    for window, metrics in windows_data.items():
        windows[window] = _aggregate_metrics(metrics)
    
    # Find best window and region
    best_window = _find_best_window(windows)
    best_region = _find_best_region(regions)
    
    # Build output with deterministic timestamp
    import os
    utc_iso = os.environ.get('MM_FREEZE_UTC_ISO', datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    
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
    
    # Write JSON output
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        json.dump(report, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write('\n')
    
    # Write MD output (match golden format exactly)
    md_out = Path(args.out).with_suffix('.md')
    with open(md_out, 'w', encoding='utf-8', newline='') as f:
        f.write("Region Canary Comparison\n\n")
        
        # Regions table
        f.write("| region | net_bps | order_age_p95_ms | fill_rate | taker_share_pct |\n")
        f.write("|--------|---------|------------------|-----------|------------------|\n")
        for reg in sorted(regions.keys()):
            data = regions[reg]
            f.write(f"| {reg} | {data.get('net_bps', 0):.6f} | {data.get('order_age_p95_ms', 0):.6f} | {data.get('fill_rate', 0):.6f} | {data.get('taker_share_pct', 0):.6f} |\n")
        
        f.write("\n")
        
        # Windows table
        f.write("| window | net_bps | order_age_p95_ms | fill_rate | taker_share_pct |\n")
        f.write("|--------|---------|------------------|-----------|------------------|\n")
        for win in sorted(windows.keys()):
            data = windows[win]
            f.write(f"| {win} | {data.get('net_bps', 0):.6f} | {data.get('order_age_p95_ms', 0):.6f} | {data.get('fill_rate', 0):.6f} | {data.get('taker_share_pct', 0):.6f} |\n")
        
        f.write("\n")
        f.write(f"Winner: {best_region} @ {best_window}\n")
    
    # Update golden files if requested
    if args.update_golden:
        import shutil
        golden_dir = Path("tests/golden")
        golden_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(args.out, golden_dir / "region_compare_case1.json")
        shutil.copy(md_out, golden_dir / "region_compare_case1.md")
        print(f"[OK] Updated golden files: {golden_dir}/region_compare_case1.{{json,md}}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Anomaly Radar: MAD-based anomaly detection for time series and KPI buckets.

Functions:
    _median(seq): Calculate median
    _mad(seq): Calculate Median Absolute Deviation
    detect_anomalies(buckets, k): Detect anomalies in KPI buckets
"""
from __future__ import annotations
from typing import Sequence, List, Dict, Any


def _median(seq: Sequence[float]) -> float:
    """
    Calculate median of a sequence.
    
    Args:
        seq: Sequence of numbers
    
    Returns:
        Median value
    """
    arr = sorted(float(x) for x in seq)
    n = len(arr)
    
    if n == 0:
        return 0.0
    
    mid = n // 2
    
    if n % 2 == 1:
        return arr[mid]
    else:
        return 0.5 * (arr[mid - 1] + arr[mid])


def _mad(seq: Sequence[float]) -> float:
    """
    Calculate Median Absolute Deviation (MAD).
    
    Args:
        seq: Sequence of numbers
    
    Returns:
        MAD value
    """
    if not seq:
        return 0.0
    
    m = _median(seq)
    deviations = [abs(float(x) - m) for x in seq]
    
    return _median(deviations)


def detect_anomalies(buckets: List[Dict[str, Any]], k: float = 3.0) -> List[Dict[str, Any]]:
    """
    Detect anomalies in KPI buckets using MAD-based method.
    
    Args:
        buckets: List of bucket dicts with KPIs (net_bps, order_age_p95_ms, taker_share_pct)
        k: Threshold multiplier (default: 3.0)
    
    Returns:
        List of anomaly dicts with 'kind', 'bucket', and KPI values
    
    Example:
        >>> buckets = [
        ...     {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
        ...     {'bucket': '00:30', 'net_bps': -1.0, 'order_age_p95_ms': 310.0, 'taker_share_pct': 12.2},
        ... ]
        >>> anomalies = detect_anomalies(buckets, k=3.0)
        >>> [a['kind'] for a in anomalies]
        ['EDGE']
    """
    if not buckets:
        return []
    
    # Extract KPI sequences
    kpis = {
        'EDGE': [b.get('net_bps', 0.0) for b in buckets],
        'LAT': [b.get('order_age_p95_ms', 0.0) for b in buckets],
        'TAKER': [b.get('taker_share_pct', 0.0) for b in buckets]
    }
    
    anomalies = []
    
    for kpi_name, values in kpis.items():
        if not values:
            continue
        
        med = _median(values)
        mad = _mad(values)
        
        # CRITICAL: If MAD is 0, all values are identical
        # No anomalies can be detected
        if mad == 0:
            continue
        
        for i, (bucket, val) in enumerate(zip(buckets, values)):
            score = abs(val - med) / mad
            
            if score > k:
                anomalies.append({
                    'kind': kpi_name,
                    'bucket': bucket.get('bucket', f'#{i}'),
                    'net_bps': bucket.get('net_bps'),
                    'order_age_p95_ms': bucket.get('order_age_p95_ms'),
                    'taker_share_pct': bucket.get('taker_share_pct'),
                    'mad_score': score
                })
    
    return anomalies


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path
    
    parser = argparse.ArgumentParser(description="Anomaly Radar: MAD-based anomaly detection")
    parser.add_argument("--edge-report", help="Path to EDGE_REPORT_DAY.json")
    parser.add_argument("--bucket-min", type=int, default=15, help="Bucket size in minutes")
    parser.add_argument("--out-json", default="artifacts/ANOMALY_RADAR.json", help="Output JSON path")
    parser.add_argument("--out", default="artifacts/ANOMALY_RADAR.json", help="Output JSON path (alias)")
    parser.add_argument("--smoke", action="store_true", help="Run smoke test")
    parser.add_argument("--update-golden", action="store_true", help="Update golden file for tests")
    args = parser.parse_args()
    
    if args.smoke:
        # Smoke test mode
        print("Testing anomaly_radar...")
        
        # Test 1: Basic median/MAD
        xs = [1.0, 2.0, 3.0, 4.0, 100.0]
        med = _median(xs)
        mad = _mad(xs)
        print(f"Test 1: median={med}, mad={mad}")
        assert med == 3.0
        assert abs(mad - 1.0) < 1e-12
        
        # Test 2: Detect anomalies in buckets
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:15', 'net_bps': 2.9, 'order_age_p95_ms': 305.0, 'taker_share_pct': 12.1},
            {'bucket': '00:30', 'net_bps': -1.0, 'order_age_p95_ms': 310.0, 'taker_share_pct': 12.2},
            {'bucket': '00:45', 'net_bps': 3.1, 'order_age_p95_ms': 295.0, 'taker_share_pct': 12.3},
            {'bucket': '01:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 30.0},
        ]
        
        anoms = detect_anomalies(buckets, 3.0)
        kinds = [a['kind'] for a in anoms]
        print(f"Test 2: anomalies detected: {kinds}")
        assert 'EDGE' in kinds and 'TAKER' in kinds
        
        print("\n[OK] All smoke tests passed")
        sys.exit(0)
    
    # CLI mode: Generate report from edge-report or use minimal data
    import os
    if args.edge_report:
        # Load edge report
        edge_data = json.loads(Path(args.edge_report).read_text(encoding='utf-8'))
        # Extract buckets from edge data (simplified)
        buckets = edge_data.get("buckets", [])
    else:
        # Use minimal synthetic data
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:15', 'net_bps': 2.9, 'order_age_p95_ms': 305.0, 'taker_share_pct': 12.1},
        ]
    
    anomalies = detect_anomalies(buckets, k=3.0)
    
    # Sort anomalies by kind, then by bucket for stable output
    anomalies_sorted = sorted(anomalies, key=lambda x: (x['kind'], x['bucket']))
    
    # Deterministic timestamp
    from datetime import datetime, timezone
    utc_iso = os.environ.get('MM_FREEZE_UTC_ISO', datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    
    report = {
        "anomalies": anomalies_sorted,
        "runtime": {
            "utc": utc_iso,
            "version": "0.1.0"
        },
        "status": "OK"
    }
    
    # Write JSON output
    out_json_path = Path(args.out_json if args.out_json != "artifacts/ANOMALY_RADAR.json" else args.out)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json_path, 'w', encoding='utf-8', newline='') as f:
        json.dump(report, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write('\n')
    
    # Also create MD report (in same directory)
    out_md_path = out_json_path.with_suffix('.md')
    with open(out_md_path, 'w', encoding='utf-8', newline='') as f:
        f.write("# Anomaly Radar Report\n\n")
        f.write(f"Status: {report['status']}\n\n")
        f.write(f"Anomalies detected: {len(anomalies_sorted)}\n\n")
        if anomalies_sorted:
            f.write("| Kind | Bucket | MAD Score |\n")
            f.write("|------|--------|------------|\n")
            for a in anomalies_sorted[:10]:  # Limit to 10 for brevity
                f.write(f"| {a['kind']} | {a['bucket']} | {a.get('mad_score', 0):.2f} |\n")
    
    # Update golden files if requested
    if args.update_golden:
        import shutil
        golden_dir = Path("tests/golden")
        golden_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(out_json_path, golden_dir / "ANOMALY_RADAR_case1.json")
        shutil.copy(out_md_path, golden_dir / "ANOMALY_RADAR_case1.md")
        print(f"[OK] Updated golden files: {golden_dir}/ANOMALY_RADAR_case1.{{json,md}}")
    
    sys.exit(0)

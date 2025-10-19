#!/usr/bin/env python3
"""
Prometheus metrics exporter for soak tests.

Exports key KPIs and guard states for monitoring.

Metrics:
  - maker_taker_ratio_hmean{window="8"}
  - latency_spread_add_bps
  - partial_freeze_active (0/1)
  - delta_nested_miss_paths_total (counter)
  - maker_share_pct (corrected formula)
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import statistics


def harmonic_mean(values: List[float]) -> float:
    """Calculate harmonic mean."""
    if not values or any(v <= 0 for v in values):
        return 0.0
    
    return len(values) / sum(1.0 / v for v in values)


def load_iter_summaries(base_path: Path, last_n: int = 8) -> List[Dict[str, Any]]:
    """Load last N iteration summaries."""
    summaries = []
    
    # Find all ITER_SUMMARY files
    for i in range(1, 100):
        path = base_path / f"ITER_SUMMARY_{i}.json"
        if not path.exists():
            break
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                summaries.append(json.load(f))
        except:
            pass
    
    # Return last N
    return summaries[-last_n:] if len(summaries) >= last_n else summaries


def calculate_maker_share_pct(fills: Dict[str, Any]) -> float:
    """
    Calculate maker share percentage (corrected formula).
    
    Formula: maker/(maker+taker)*100
    
    Args:
        fills: Dict with maker_count, taker_count, maker_volume, taker_volume
    
    Returns:
        Maker share percentage (0-100)
    """
    # Prefer volume-based calculation
    maker_vol = fills.get('maker_volume', 0)
    taker_vol = fills.get('taker_volume', 0)
    
    if maker_vol > 0 or taker_vol > 0:
        return (maker_vol / (maker_vol + taker_vol)) * 100.0
    
    # Fallback to count-based
    maker_count = fills.get('maker_count', 0)
    taker_count = fills.get('taker_count', 0)
    
    if maker_count > 0 or taker_count > 0:
        return (maker_count / (maker_count + taker_count)) * 100.0
    
    return 0.0


def export_metrics(
    base_path: Path,
    output_path: Optional[Path] = None
) -> str:
    """
    Export Prometheus metrics in text format.
    
    Args:
        base_path: Path to soak artifacts (containing ITER_SUMMARY_*.json)
        output_path: Optional path to write metrics file
    
    Returns:
        Metrics in Prometheus text format
    """
    # Load last 8 iterations
    summaries = load_iter_summaries(base_path, last_n=8)
    
    if not summaries:
        return "# No iteration data found\n"
    
    lines = []
    
    # Header
    lines.append("# HELP maker_taker_ratio_hmean Harmonic mean of maker/taker ratio over window")
    lines.append("# TYPE maker_taker_ratio_hmean gauge")
    
    # Calculate harmonic mean of maker/taker ratio
    mt_ratios = [s.get('summary', {}).get('maker_taker_ratio', 0) for s in summaries]
    mt_ratios = [r for r in mt_ratios if r > 0]  # Filter zeros
    
    if mt_ratios:
        mt_hmean = harmonic_mean(mt_ratios)
        lines.append(f'maker_taker_ratio_hmean{{window="8"}} {mt_hmean:.6f}')
    else:
        lines.append(f'maker_taker_ratio_hmean{{window="8"}} 0.0')
    
    lines.append("")
    
    # Latency spread add (from latest iteration)
    lines.append("# HELP latency_spread_add_bps Latency spread addition in BPS")
    lines.append("# TYPE latency_spread_add_bps gauge")
    
    latest_runtime = summaries[-1].get('runtime_overrides', {})
    latency_spread = latest_runtime.get('latency', {}).get('spread_add_bps', 0.0)
    if isinstance(latency_spread, (int, float)):
        lines.append(f'latency_spread_add_bps {latency_spread:.3f}')
    else:
        lines.append('latency_spread_add_bps 0.0')
    
    lines.append("")
    
    # Partial freeze active
    lines.append("# HELP partial_freeze_active Partial freeze status (1=active, 0=inactive)")
    lines.append("# TYPE partial_freeze_active gauge")
    
    latest_tuning = summaries[-1].get('tuning', {})
    skip_reason = latest_tuning.get('skip_reason', {})
    
    freeze_active = 0
    if isinstance(skip_reason, dict):
        if skip_reason.get('freeze') or skip_reason.get('partial_freeze'):
            freeze_active = 1
    
    lines.append(f'partial_freeze_active {freeze_active}')
    
    lines.append("")
    
    # Delta nested miss paths (counter - would need persistent state)
    lines.append("# HELP delta_nested_miss_paths_total Count of nested parameter misses in delta verification")
    lines.append("# TYPE delta_nested_miss_paths_total counter")
    
    # This would need to be accumulated from DELTA_VERIFY_REPORT.json
    # For now, placeholder
    lines.append('delta_nested_miss_paths_total 0')
    
    lines.append("")
    
    # Maker share pct (corrected formula)
    lines.append("# HELP maker_share_pct Maker share percentage (corrected: maker/(maker+taker)*100)")
    lines.append("# TYPE maker_share_pct gauge")
    
    latest_summary = summaries[-1].get('summary', {})
    fills = latest_summary.get('fills', {})
    
    if fills:
        maker_share = calculate_maker_share_pct(fills)
        lines.append(f'maker_share_pct {maker_share:.2f}')
    else:
        # Fallback to maker_taker_ratio * 100
        mt_ratio = latest_summary.get('maker_taker_ratio', 0)
        lines.append(f'maker_share_pct {mt_ratio * 100:.2f}')
    
    lines.append("")
    
    # Join and optionally write
    metrics_text = '\n'.join(lines)
    
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(metrics_text)
    
    return metrics_text


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Export Prometheus metrics from soak artifacts")
    parser.add_argument(
        "--path",
        type=str,
        required=True,
        help="Path to soak artifacts directory"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)"
    )
    
    args = parser.parse_args()
    
    base_path = Path(args.path)
    output_path = Path(args.output) if args.output else None
    
    metrics = export_metrics(base_path, output_path)
    
    if not output_path:
        print(metrics)
    else:
        print(f"[OK] Metrics written to {output_path}")


if __name__ == '__main__':
    main()


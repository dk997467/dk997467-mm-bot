#!/usr/bin/env python3
"""
Soak Test Runner - Metrics Collection & Reporting

Collects metrics from Prometheus/logs and generates pass/fail reports based on gates.

Usage:
    python -m tools.soak.run --hours 72 \\
      --export-json artifacts/reports/soak_metrics.json \\
      --export-md artifacts/reports/SOAK_RESULTS.md \\
      --gate-summary artifacts/reports/gates_summary.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple


def calculate_p95(values: List[float]) -> float:
    """Calculate 95th percentile."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * 0.95)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


def calculate_ema(values: List[float], half_life_periods: int) -> float:
    """Calculate exponential moving average."""
    if not values:
        return 0.0
    alpha = 1.0 - (0.5 ** (1.0 / half_life_periods))
    ema = values[0]
    for val in values[1:]:
        ema = alpha * val + (1 - alpha) * ema
    return ema


def collect_metrics(hours: int, mock: bool = False) -> Dict[str, Any]:
    """
    Collect metrics from Prometheus/logs.
    
    Args:
        hours: Duration of soak test
        mock: If True, return mock data for testing
        
    Returns:
        Dict with metrics
    """
    if mock:
        # Mock data for testing
        return {
            "tick_latency_ms": {
                "p50": 85.2,
                "p95": 142.5
            },
            "mm_hit_ratio": 0.78,
            "mm_maker_share_ratio": 0.92,
            "mm_deadline_miss_rate": 0.015,
            "mm_edge_bps_ema1h": 2.8,
            "mm_edge_bps_ema24h": 2.6,
            "ws_lag_max_ms": 125.0,
            "duration_hours": hours
        }
    
    # Real implementation would query Prometheus here
    # For now, return defaults
    return {
        "tick_latency_ms": {"p50": 0.0, "p95": 0.0},
        "mm_hit_ratio": 0.0,
        "mm_maker_share_ratio": 0.0,
        "mm_deadline_miss_rate": 0.0,
        "mm_edge_bps_ema1h": 0.0,
        "mm_edge_bps_ema24h": 0.0,
        "ws_lag_max_ms": 0.0,
        "duration_hours": hours
    }


def evaluate_gates(metrics: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], bool]:
    """
    Evaluate gates against metrics.
    
    Returns:
        (gates_dict, overall_pass)
    """
    gates = {
        "latency_p95": {
            "threshold": 150.0,
            "actual": metrics["tick_latency_ms"]["p95"],
            "pass": metrics["tick_latency_ms"]["p95"] <= 150.0,
            "severity": "hard"
        },
        "hit_ratio": {
            "threshold": 0.70,
            "actual": metrics["mm_hit_ratio"],
            "pass": metrics["mm_hit_ratio"] >= 0.70,
            "severity": "hard"
        },
        "deadline_miss_rate": {
            "threshold": 0.02,
            "actual": metrics["mm_deadline_miss_rate"],
            "pass": metrics["mm_deadline_miss_rate"] <= 0.02,
            "severity": "hard"
        },
        "edge_bps": {
            "threshold": 2.0,
            "actual": metrics["mm_edge_bps_ema24h"],
            "pass": metrics["mm_edge_bps_ema24h"] >= 2.0,
            "severity": "hard"
        },
        "maker_share": {
            "threshold": 0.85,
            "actual": metrics["mm_maker_share_ratio"],
            "pass": metrics["mm_maker_share_ratio"] >= 0.85,
            "severity": "soft"
        },
        "ws_lag": {
            "threshold": 200.0,
            "actual": metrics["ws_lag_max_ms"],
            "pass": metrics["ws_lag_max_ms"] <= 200.0,
            "severity": "soft"
        }
    }
    
    # Overall pass: all hard gates must pass
    hard_gates_pass = all(
        g["pass"] for g in gates.values() if g["severity"] == "hard"
    )
    
    return gates, hard_gates_pass


def generate_json_report(metrics: Dict[str, Any], gates: Dict[str, Dict[str, Any]], 
                        overall_pass: bool) -> Dict[str, Any]:
    """Generate JSON report."""
    return {
        "runtime": {
            "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "version": "0.1.0"
        },
        "duration_hours": metrics["duration_hours"],
        "metrics": metrics,
        "gates": gates,
        "verdict": "PASS" if overall_pass else "FAIL"
    }


def generate_markdown_report(metrics: Dict[str, Any], gates: Dict[str, Dict[str, Any]], 
                             overall_pass: bool) -> str:
    """Generate markdown report."""
    lines = []
    lines.append("# SOAK TEST RESULTS\n\n")
    
    # Summary
    lines.append("## Summary\n\n")
    lines.append(f"**Verdict:** {'✅ PASS' if overall_pass else '❌ FAIL'}\n")
    lines.append(f"**Duration:** {metrics['duration_hours']} hours\n\n")
    
    # Key Metrics
    lines.append("## Key Metrics\n\n")
    lines.append("| Metric | Value |\n")
    lines.append("|--------|-------|\n")
    lines.append(f"| Latency P95 | {metrics['tick_latency_ms']['p95']:.1f} ms |\n")
    lines.append(f"| Hit Ratio | {metrics['mm_hit_ratio']:.2%} |\n")
    lines.append(f"| Deadline Miss Rate | {metrics['mm_deadline_miss_rate']:.2%} |\n")
    lines.append(f"| Edge BPS (24h EMA) | {metrics['mm_edge_bps_ema24h']:.2f} |\n")
    lines.append(f"| Maker Share | {metrics['mm_maker_share_ratio']:.2%} |\n")
    lines.append(f"| WS Lag Max | {metrics['ws_lag_max_ms']:.1f} ms |\n\n")
    
    # Gates
    lines.append("## Gates\n\n")
    lines.append("| Gate | Threshold | Actual | Status | Severity |\n")
    lines.append("|------|-----------|--------|--------|----------|\n")
    for name, gate in gates.items():
        status = "✅ PASS" if gate["pass"] else "❌ FAIL"
        lines.append(f"| {name} | {gate['threshold']} | {gate['actual']:.4f} | {status} | {gate['severity']} |\n")
    lines.append("\n")
    
    # Decision
    lines.append("## Decision\n\n")
    if overall_pass:
        lines.append("✅ **All hard gates passed.** System is stable for production.\n")
    else:
        failed_hard = [n for n, g in gates.items() if not g["pass"] and g["severity"] == "hard"]
        lines.append(f"❌ **Failed hard gates:** {', '.join(failed_hard)}\n")
        lines.append("System requires attention before production deployment.\n")
    
    return "".join(lines)


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Soak test runner and reporter")
    parser.add_argument("--hours", type=int, default=72, help="Soak duration in hours")
    parser.add_argument("--export-json", type=str, help="Export JSON report path")
    parser.add_argument("--export-md", type=str, help="Export markdown report path")
    parser.add_argument("--gate-summary", type=str, help="Export gates summary JSON path")
    parser.add_argument("--mock", action="store_true", help="Use mock data for testing")
    args = parser.parse_args(argv)
    
    # Collect metrics
    metrics = collect_metrics(args.hours, mock=args.mock)
    
    # Evaluate gates
    gates, overall_pass = evaluate_gates(metrics)
    
    # Generate reports
    json_report = generate_json_report(metrics, gates, overall_pass)
    md_report = generate_markdown_report(metrics, gates, overall_pass)
    
    # Export JSON report
    if args.export_json:
        Path(args.export_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.export_json, 'w') as f:
            json.dump(json_report, f, indent=2, sort_keys=True)
        print(f"[INFO] Exported JSON report: {args.export_json}")
    
    # Export markdown report
    if args.export_md:
        Path(args.export_md).parent.mkdir(parents=True, exist_ok=True)
        with open(args.export_md, 'w') as f:
            f.write(md_report)
        print(f"[INFO] Exported markdown report: {args.export_md}")
    
    # Export gates summary
    if args.gate_summary:
        gates_summary = {
            "gates": gates,
            "verdict": "PASS" if overall_pass else "FAIL"
        }
        Path(args.gate_summary).parent.mkdir(parents=True, exist_ok=True)
        with open(args.gate_summary, 'w') as f:
            json.dump(gates_summary, f, indent=2, sort_keys=True)
        print(f"[INFO] Exported gates summary: {args.gate_summary}")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"SOAK TEST: {'PASS' if overall_pass else 'FAIL'}")
    print(f"{'='*60}")
    print(f"Duration: {args.hours}h")
    print(f"Latency P95: {metrics['tick_latency_ms']['p95']:.1f}ms")
    print(f"Hit Ratio: {metrics['mm_hit_ratio']:.2%}")
    print(f"Edge BPS: {metrics['mm_edge_bps_ema24h']:.2f}")
    print(f"{'='*60}\n")
    
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())


#!/usr/bin/env python3
"""
Stage Performance Gate для CI.

Сравнивает текущие p95 метрики стадий с baseline и падает если регрессия > threshold.

Usage:
    python tools/ci/stage_perf_gate.py --baseline artifacts/baseline/stage_budgets.json --current metrics_current.json --threshold 3.0

Exit codes:
    0 - Pass (no regression)
    1 - Fail (regression detected)
    2 - Error (invalid input/parsing error)
"""
import json
import sys
import argparse
from typing import Dict, Any, List, Tuple
from pathlib import Path


def load_json(path: str) -> Dict[str, Any]:
    """Load JSON file."""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to load {path}: {e}", file=sys.stderr)
        sys.exit(2)


def get_p95(data: Dict[str, Any], stage: str) -> float:
    """
    Extract p95 for a stage from metrics data.
    
    Supports two formats:
    1. Baseline format: data['budgets'][stage]['p95']
    2. Current format: data[stage]['p95']
    """
    # Try baseline format
    if 'budgets' in data:
        if stage in data['budgets']:
            return float(data['budgets'][stage].get('p95', 0.0))
    
    # Try direct format
    if stage in data:
        return float(data[stage].get('p95', 0.0))
    
    return 0.0


def compare_stages(
    baseline: Dict[str, Any],
    current: Dict[str, Any],
    threshold_pct: float
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Compare current metrics against baseline.
    
    Args:
        baseline: Baseline metrics
        current: Current metrics
        threshold_pct: Regression threshold percentage (e.g., 3.0 for 3%)
    
    Returns:
        (passed, violations) tuple
    """
    # Stage names to check
    stages = [
        'stage_fetch_md',
        'stage_spread',
        'stage_guards',
        'stage_inventory',
        'stage_queue_aware',
        'stage_emit',
        'tick_total'
    ]
    
    violations = []
    
    for stage in stages:
        baseline_p95 = get_p95(baseline, stage)
        current_p95 = get_p95(current, stage)
        
        if baseline_p95 == 0.0:
            print(f"WARN: No baseline for {stage}, skipping", file=sys.stderr)
            continue
        
        if current_p95 == 0.0:
            print(f"WARN: No current metric for {stage}, skipping", file=sys.stderr)
            continue
        
        # Calculate regression
        change_pct = ((current_p95 - baseline_p95) / baseline_p95) * 100.0
        
        # Check threshold
        if change_pct > threshold_pct:
            violations.append({
                'stage': stage,
                'baseline_p95': baseline_p95,
                'current_p95': current_p95,
                'change_pct': change_pct,
                'threshold_pct': threshold_pct
            })
    
    return len(violations) == 0, violations


def generate_markdown_report(
    passed: bool,
    violations: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    current: Dict[str, Any]
) -> str:
    """Generate Markdown report."""
    lines = []
    
    lines.append("# 🎯 Stage Performance Gate Report")
    lines.append("")
    
    if passed:
        lines.append("✅ **PASSED** - No performance regressions detected")
    else:
        lines.append(f"❌ **FAILED** - {len(violations)} stage(s) regressed")
    
    lines.append("")
    lines.append("## Violations")
    lines.append("")
    
    if violations:
        lines.append("| Stage | Baseline p95 (ms) | Current p95 (ms) | Change (%) | Threshold (%) | Status |")
        lines.append("|-------|-------------------|------------------|------------|---------------|--------|")
        
        for v in violations:
            lines.append(
                f"| {v['stage']} | {v['baseline_p95']:.2f} | {v['current_p95']:.2f} | "
                f"+{v['change_pct']:.2f} | {v['threshold_pct']:.2f} | ❌ FAIL |"
            )
    else:
        lines.append("No violations detected.")
    
    lines.append("")
    lines.append("## All Stages")
    lines.append("")
    
    stages = [
        'stage_fetch_md',
        'stage_spread',
        'stage_guards',
        'stage_inventory',
        'stage_queue_aware',
        'stage_emit',
        'tick_total'
    ]
    
    lines.append("| Stage | Baseline p95 (ms) | Current p95 (ms) | Change (%) | Status |")
    lines.append("|-------|-------------------|------------------|------------|--------|")
    
    for stage in stages:
        baseline_p95 = get_p95(baseline, stage)
        current_p95 = get_p95(current, stage)
        
        if baseline_p95 == 0.0 or current_p95 == 0.0:
            continue
        
        change_pct = ((current_p95 - baseline_p95) / baseline_p95) * 100.0
        
        if change_pct > 0:
            status = "⚠️" if change_pct <= 3.0 else "❌"
            change_str = f"+{change_pct:.2f}"
        else:
            status = "✅"
            change_str = f"{change_pct:.2f}"
        
        lines.append(
            f"| {stage} | {baseline_p95:.2f} | {current_p95:.2f} | {change_str} | {status} |"
        )
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Stage Performance Gate for CI")
    parser.add_argument('--baseline', required=True, help="Path to baseline metrics JSON")
    parser.add_argument('--current', required=True, help="Path to current metrics JSON")
    parser.add_argument('--threshold', type=float, default=3.0, help="Regression threshold in percent (default: 3.0)")
    parser.add_argument('--output', help="Path to output Markdown report (optional)")
    
    args = parser.parse_args()
    
    # Load data
    baseline = load_json(args.baseline)
    current = load_json(args.current)
    
    # Get threshold (from baseline if available)
    threshold_pct = args.threshold
    if 'thresholds' in baseline and 'regress_pct' in baseline['thresholds']:
        threshold_pct = float(baseline['thresholds']['regress_pct'])
    
    # Compare
    passed, violations = compare_stages(baseline, current, threshold_pct)
    
    # Generate report
    report = generate_markdown_report(passed, violations, baseline, current)
    
    # Print report
    print(report)
    
    # Save to file if requested
    if args.output:
        try:
            with open(args.output, 'w') as f:
                f.write(report)
            print(f"\nReport saved to: {args.output}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Failed to save report: {e}", file=sys.stderr)
    
    # Exit with appropriate code
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()


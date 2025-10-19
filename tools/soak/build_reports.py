#!/usr/bin/env python3
"""
Soak Test Report Builder - Generates comprehensive analysis reports.

Generates:
  - POST_SOAK_SNAPSHOT.json (machine-readable summary)
  - POST_SOAK_AUDIT.md (detailed metrics + sparklines)
  - RECOMMENDATIONS.md (tuning suggestions)
  - FAILURES.md (failure analysis)

Usage:
    python -m tools.soak.build_reports --src artifacts/soak/latest --out artifacts/soak/latest/reports/analysis
    python -m tools.soak.build_reports --src "artifacts/soak/latest 1" --out release/reports
"""

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional


# KPI Targets (last-8 iterations)
KPI_TARGETS = {
    "maker_taker_ratio": {"min": 0.83, "direction": "up"},
    "p95_latency_ms": {"max": 340, "direction": "down"},
    "risk_ratio": {"max": 0.40, "direction": "down"},
    "net_bps": {"min": 2.5, "direction": "up"},
}


def load_iter_summaries(soak_dir: Path) -> Dict[int, Dict[str, Any]]:
    """Load all ITER_SUMMARY_*.json files."""
    summaries = {}
    for i in range(1, 100):  # Support up to 99 iterations
        path = soak_dir / f"ITER_SUMMARY_{i}.json"
        if not path.exists():
            break
        try:
            with open(path, 'r', encoding='utf-8') as f:
                summaries[i] = json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to load {path}: {e}", file=sys.stderr)
    
    return summaries


def extract_kpi_metrics(summaries: Dict[int, Dict[str, Any]]) -> Dict[str, List[float]]:
    """Extract key KPI metrics from all iterations."""
    metrics = {
        'maker_taker_ratio': [],
        'p95_latency_ms': [],
        'risk_ratio': [],
        'net_bps': [],
        'adverse_bps_p95': [],
        'slippage_bps_p95': [],
        'cancel_ratio': [],
    }
    
    for iter_num in sorted(summaries.keys()):
        summary = summaries[iter_num].get('summary', {})
        
        for key in metrics.keys():
            metrics[key].append(summary.get(key, 0.0))
    
    return metrics


def calc_stats(values: List[float]) -> Dict[str, float]:
    """Calculate min/max/mean/median/trend for a metric."""
    if not values:
        return {'min': 0, 'max': 0, 'mean': 0, 'median': 0, 'trend': 'flat'}
    
    # Calculate trend (simple: compare first quarter vs last quarter)
    q1_avg = statistics.mean(values[:len(values)//4]) if len(values) >= 4 else values[0]
    q4_avg = statistics.mean(values[-len(values)//4:]) if len(values) >= 4 else values[-1]
    
    if q4_avg > q1_avg * 1.05:
        trend = 'up'
    elif q4_avg < q1_avg * 0.95:
        trend = 'down'
    else:
        trend = 'flat'
    
    return {
        'min': min(values),
        'max': max(values),
        'mean': statistics.mean(values),
        'median': statistics.median(values),
        'trend': trend
    }


def extract_tuning_info(summaries: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """Extract tuning/delta application info."""
    applied_iters = []
    all_changed_keys = set()
    skip_reasons = {}
    
    for iter_num in sorted(summaries.keys()):
        tuning = summaries[iter_num].get('tuning', {})
        
        if tuning.get('applied'):
            applied_iters.append(iter_num)
            changed_keys = tuning.get('changed_keys', [])
            all_changed_keys.update(changed_keys)
        
        skip_reason = tuning.get('skip_reason')
        if skip_reason and skip_reason != "":
            reason_key = skip_reason if isinstance(skip_reason, str) else skip_reason.get('note', 'unknown')
            skip_reasons[reason_key] = skip_reasons.get(reason_key, 0) + 1
    
    return {
        'applied_count': len(applied_iters),
        'applied_iters': applied_iters,
        'changed_keys': sorted(list(all_changed_keys)),
        'skip_reasons': skip_reasons
    }


def extract_guards_info(summaries: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """Extract guard activation info."""
    guards = {
        'latency_soft': 0,
        'latency_hard': 0,
        'oscillation': 0,
        'velocity': 0,
        'cooldown': 0,
        'freeze': 0,
    }
    
    guard_iters = {k: [] for k in guards.keys()}
    
    for iter_num in sorted(summaries.keys()):
        tuning = summaries[iter_num].get('tuning', {})
        skip_reason = tuning.get('skip_reason', {})
        
        if isinstance(skip_reason, dict):
            for guard_type in ['oscillation', 'velocity', 'cooldown', 'freeze']:
                if skip_reason.get(guard_type):
                    guards[guard_type] += 1
                    guard_iters[guard_type].append(iter_num)
        
        # Check for latency buffer triggers in reasons
        tuning_reasons = tuning.get('reasons', [])
        if isinstance(tuning_reasons, list):
            for reason in tuning_reasons:
                reason_str = str(reason)
                if 'LATENCY_BUFFER' in reason_str:
                    guards['latency_soft'] += 1
                    guard_iters['latency_soft'].append(iter_num)
                elif 'LATENCY_HARD' in reason_str:
                    guards['latency_hard'] += 1
                    guard_iters['latency_hard'].append(iter_num)
    
    return {
        'counts': guards,
        'iterations': guard_iters
    }


def generate_sparkline(values: List[float], width: int = 40) -> str:
    """Generate ASCII sparkline."""
    if not values or len(values) < 2:
        return " " * width
    
    min_val = min(values)
    max_val = max(values)
    range_val = max_val - min_val
    
    if range_val == 0:
        return "-" * width
    
    # Use simple ASCII characters for Windows compatibility
    bars = ' -=+#'
    
    spark = []
    step = len(values) / width
    
    for i in range(width):
        idx = int(i * step)
        if idx < len(values):
            val = values[idx]
            normalized = (val - min_val) / range_val
            bar_idx = int(normalized * (len(bars) - 1))
            spark.append(bars[bar_idx])
        else:
            spark.append(' ')
    
    return ''.join(spark)


def analyze_last_n(summaries: Dict[int, Dict[str, Any]], n: int = 8) -> Dict[str, Any]:
    """Analyze last N iterations."""
    iter_nums = sorted(summaries.keys())
    last_n_nums = iter_nums[-n:] if len(iter_nums) >= n else iter_nums
    last_n = {k: v for k, v in summaries.items() if k in last_n_nums}
    
    metrics = extract_kpi_metrics(last_n)
    
    return {
        'iterations': last_n_nums,
        'metrics': {k: calc_stats(v) for k, v in metrics.items()},
        'raw_values': metrics
    }


def check_goals(last_n_analysis: Dict[str, Any]) -> Dict[str, bool]:
    """Check if last-N goals are met."""
    metrics = last_n_analysis['metrics']
    
    return {
        'maker_taker_ok': metrics['maker_taker_ratio']['mean'] >= KPI_TARGETS['maker_taker_ratio']['min'],
        'p95_latency_ok': metrics['p95_latency_ms']['max'] <= KPI_TARGETS['p95_latency_ms']['max'],
        'risk_ok': metrics['risk_ratio']['median'] <= KPI_TARGETS['risk_ratio']['max'],
        'net_bps_ok': metrics['net_bps']['mean'] >= KPI_TARGETS['net_bps']['min'],
    }


def generate_snapshot(data: Dict[str, Any], timestamp: str) -> Dict[str, Any]:
    """Generate POST_SOAK_SNAPSHOT.json."""
    last_n = data['last_n']
    goals = data['goals']
    guards = data['guards_info']
    tuning = data['tuning_info']
    
    # Determine verdict
    all_goals_met = all(goals.values())
    if all_goals_met:
        verdict = "PASS"
    elif goals.get('risk_ok') and goals.get('net_bps_ok'):
        verdict = "WARN"
    else:
        verdict = "FAIL"
    
    # KPI last-N summary
    kpi_last_n = {}
    for metric_name, stats in last_n['metrics'].items():
        kpi_last_n[metric_name] = {
            'mean': round(stats['mean'], 4),
            'median': round(stats['median'], 4),
            'min': round(stats['min'], 4),
            'max': round(stats['max'], 4),
            'trend': stats['trend']
        }
    
    return {
        'schema_version': '1.2',
        'timestamp': timestamp,
        'verdict': verdict,
        'iterations_total': len(data['summaries']),
        'iterations_analyzed': last_n['iterations'],
        'pass_count_last_n': sum(1 for g in goals.values() if g),
        'kpi_last_n': kpi_last_n,
        'goals_met': goals,
        'guards_last_n': {
            'counts': guards['counts'],
            'iterations': {k: v for k, v in guards['iterations'].items() if v}
        },
        'tuning_summary': {
            'applied_count': tuning['applied_count'],
            'applied_iterations': tuning['applied_iters'],
            'changed_keys': tuning['changed_keys'],
            'skip_reasons': tuning['skip_reasons']
        },
        'freeze_ready': all_goals_met,
        'anomalies_count': sum(1 for c in guards['counts'].values() if c > 5),
    }


def generate_audit_md(data: Dict[str, Any], timestamp: str) -> str:
    """Generate POST_SOAK_AUDIT.md."""
    all_stats = data['all_stats']
    last_n_stats = data['last_n']['metrics']
    guards = data['guards_info']
    tuning = data['tuning_info']
    goals = data['goals']
    all_metrics = data['all_metrics']
    
    n = len(data['last_n']['iterations'])
    
    lines = []
    
    # Header
    lines.append("# Post-Soak Audit Report")
    lines.append("")
    lines.append(f"**Generated:** {timestamp}")
    lines.append(f"**Iterations:** {len(data['summaries'])} (analyzing last-{n}: iterations {min(data['last_n']['iterations'])}-{max(data['last_n']['iterations'])})")
    lines.append(f"**Verdict:** {'PASS - READY FOR PROD-FREEZE' if all(goals.values()) else 'WARN/FAIL - Additional tuning recommended'}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Executive Summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("| Metric | Target | Last-{} Value | Status |".format(n))
    lines.append("|--------|--------|--------------|--------|")
    
    lines.append(f"| Maker/Taker Ratio | >= {KPI_TARGETS['maker_taker_ratio']['min']:.2f} | {last_n_stats['maker_taker_ratio']['mean']:.3f} | {'[OK]' if goals['maker_taker_ok'] else '[FAIL]'} |")
    lines.append(f"| P95 Latency | <= {KPI_TARGETS['p95_latency_ms']['max']} ms | {last_n_stats['p95_latency_ms']['max']:.1f} ms | {'[OK]' if goals['p95_latency_ok'] else '[FAIL]'} |")
    lines.append(f"| Risk Ratio | <= {KPI_TARGETS['risk_ratio']['max']:.2f} | {last_n_stats['risk_ratio']['median']:.3f} | {'[OK]' if goals['risk_ok'] else '[FAIL]'} |")
    lines.append(f"| Net BPS | >= {KPI_TARGETS['net_bps']['min']:.1f} | {last_n_stats['net_bps']['mean']:.2f} | {'[OK]' if goals['net_bps_ok'] else '[FAIL]'} |")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # KPI Metrics Table (All vs Last-N)
    lines.append(f"## KPI Metrics: All Iterations vs Last-{n}")
    lines.append("")
    lines.append(f"| Metric | All (1-{len(data['summaries'])}) | Last-{n} ({min(data['last_n']['iterations'])}-{max(data['last_n']['iterations'])}) | Trend |")
    lines.append("|--------|------------|----------------|-------|")
    
    for metric_name in ['maker_taker_ratio', 'p95_latency_ms', 'risk_ratio', 'net_bps', 'adverse_bps_p95', 'slippage_bps_p95']:
        all_s = all_stats[metric_name]
        last_s = last_n_stats[metric_name]
        
        lines.append(f"| **{metric_name}** | | | |")
        lines.append(f"| - Mean | {all_s['mean']:.3f} | {last_s['mean']:.3f} | {last_s['trend']} |")
        lines.append(f"| - Median | {all_s['median']:.3f} | {last_s['median']:.3f} | |")
        lines.append(f"| - Min/Max | {all_s['min']:.3f} / {all_s['max']:.3f} | {last_s['min']:.3f} / {last_s['max']:.3f} | |")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Sparklines
    lines.append(f"## Metric Trends (ASCII Sparklines - {len(data['summaries'])} iterations)")
    lines.append("")
    lines.append("```")
    for metric_name in ['maker_taker_ratio', 'p95_latency_ms', 'risk_ratio', 'net_bps']:
        values = all_metrics[metric_name]
        spark = generate_sparkline(values, width=min(len(values), 40))
        lines.append(f"{metric_name:20s} [{spark}]")
    lines.append("```")
    lines.append("")
    lines.append("(Each character represents 1 iteration, low to high: ` `, `-`, `=`, `+`, `#`)")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Guards Summary
    lines.append("## Guards & Tuning Activity")
    lines.append("")
    lines.append("### Guard Activations")
    lines.append("")
    lines.append("| Guard Type | Count | Iterations |")
    lines.append("|------------|-------|------------|")
    
    for guard_name, count in guards['counts'].items():
        iters = guards['iterations'].get(guard_name, [])
        iters_str = ', '.join(map(str, iters[:10]))
        if len(iters) > 10:
            iters_str += f" ... (+{len(iters)-10} more)"
        lines.append(f"| {guard_name} | {count} | {iters_str or 'None'} |")
    
    lines.append("")
    lines.append("### Delta Application")
    lines.append("")
    lines.append(f"- **Applied:** {tuning['applied_count']} times (iterations: {', '.join(map(str, tuning['applied_iters']))})")
    lines.append(f"- **Changed Keys:** {', '.join(tuning['changed_keys']) if tuning['changed_keys'] else 'None'}")
    lines.append("")
    
    if tuning['skip_reasons']:
        lines.append("### Skip Reasons")
        lines.append("")
        for reason, count in tuning['skip_reasons'].items():
            lines.append(f"- **{reason}:** {count} times")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # Anomalies & Peaks
    lines.append("## Anomalies & Peaks")
    lines.append("")
    
    # Find peak iterations for each metric
    for metric_name in ['p95_latency_ms', 'risk_ratio', 'adverse_bps_p95']:
        values = all_metrics[metric_name]
        if values:
            max_val = max(values)
            max_iter = values.index(max_val) + 1
            lines.append(f"- **{metric_name} peak:** {max_val:.2f} at iteration {max_iter}")
    
    lines.append("")
    
    # Velocity guard triggers (potential false positives)
    velocity_count = guards['counts'].get('velocity', 0)
    if velocity_count > 0:
        lines.append(f"- **Velocity guard triggered {velocity_count} times** - Review if these are false positives")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # Final Assessment
    lines.append("## Final Assessment")
    lines.append("")
    
    if all(goals.values()):
        lines.append(f"[OK] **All KPI targets met for last-{n} iterations.**")
        lines.append("")
        lines.append("**Recommendation:** System is stable and ready for production freeze.")
        lines.append("")
        lines.append("**Next Steps:**")
        lines.append("1. Review RECOMMENDATIONS.md for optional optimizations")
        lines.append("2. Run delta verification to ensure 95%+ apply ratio")
        lines.append("3. Proceed with production freeze")
    else:
        failed_goals = [k for k, v in goals.items() if not v]
        lines.append(f"[WARN] **Goals not met:** {', '.join(failed_goals)}")
        lines.append("")
        lines.append("**Recommendation:** Apply tuning recommendations before production freeze.")
        lines.append("")
        lines.append("**Next Steps:**")
        lines.append("1. Review RECOMMENDATIONS.md for required changes")
        lines.append("2. Run additional iterations with recommended deltas")
        lines.append("3. Re-validate KPI targets")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Generated by soak build_reports at {timestamp}*")
    
    return '\n'.join(lines)


def generate_recommendations_md(data: Dict[str, Any], timestamp: str) -> str:
    """Generate RECOMMENDATIONS.md."""
    goals = data['goals']
    last_n_stats = data['last_n']['metrics']
    guards = data['guards_info']
    
    lines = []
    
    # Header
    lines.append("# Soak Test Recommendations")
    lines.append("")
    lines.append(f"**Generated:** {timestamp}")
    lines.append(f"**Status:** {'PROD-READY' if all(goals.values()) else 'TUNING NEEDED'}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    if all(goals.values()):
        # All goals met - optional optimizations only
        lines.append("## Status: All Goals Met [OK]")
        lines.append("")
        lines.append("All KPI targets achieved for last-N iterations. System is stable and ready for production freeze.")
        lines.append("")
        lines.append("### Optional Optimizations (Low Priority)")
        lines.append("")
        
        # Check if we can push metrics even better
        maker_taker = last_n_stats['maker_taker_ratio']['mean']
        p95_latency = last_n_stats['p95_latency_ms']['max']
        
        lines.append(f"#### 1. Maker/Taker Optimization (Current: {maker_taker*100:.1f}%)")
        lines.append("")
        if maker_taker < 0.90:
            lines.append(f"**Current:** {maker_taker:.3f}")
            lines.append(f"**Target:** 0.90+ (90%+)")
            lines.append("")
            lines.append("**Suggested Deltas:**")
            lines.append("```python")
            lines.append("base_spread_bps_delta += 0.01  # Wider spreads -> more maker")
            lines.append("replace_rate_per_min *= 0.95    # Less aggressive repricing")
            lines.append("min_interval_ms += 10           # Reduce quote churn")
            lines.append("```")
            lines.append("")
            lines.append("**Expected Impact:** +2-3% maker share, -0.5 BPS net (acceptable trade-off)")
            lines.append("")
        else:
            lines.append(f"**Current:** {maker_taker:.3f} (already excellent)")
            lines.append("No changes needed.")
            lines.append("")
        
        lines.append(f"#### 2. Latency Margin (Current: {p95_latency:.0f} ms)")
        lines.append("")
        if p95_latency > 250:
            lines.append(f"**Current:** {p95_latency:.1f} ms")
            lines.append(f"**Target:** < 250 ms (larger safety margin)")
            lines.append("")
            lines.append("**Suggested Deltas:**")
            lines.append("```python")
            lines.append("concurrency_limit *= 0.95  # Reduce load")
            lines.append("tail_age_ms += 25          # More conservative aging")
            lines.append("```")
            lines.append("")
            lines.append("**Expected Impact:** -20-30ms p95 latency, minimal BPS impact")
            lines.append("")
        else:
            lines.append(f"**Current:** {p95_latency:.1f} ms (excellent, large margin vs {KPI_TARGETS['p95_latency_ms']['max']}ms cap)")
            lines.append("No changes needed.")
            lines.append("")
        
        lines.append("#### 3. Guard Tuning")
        lines.append("")
        velocity_count = guards['counts'].get('velocity', 0)
        if velocity_count > 3:
            lines.append(f"**Velocity guard triggered {velocity_count} times** - Consider if threshold too tight:")
            lines.append("")
            lines.append("**Suggested Changes:**")
            lines.append("```python")
            lines.append("# In iter_watcher.py or config")
            lines.append("velocity_cap *= 1.1  # Relax by 10%")
            lines.append("velocity_window += 1  # Longer averaging window")
            lines.append("```")
            lines.append("")
            lines.append("**Expected Impact:** Fewer false-positive blocks, more responsive tuning")
            lines.append("")
        else:
            lines.append("Guard behavior looks good. No changes needed.")
            lines.append("")
    
    else:
        # Some goals not met - required changes
        lines.append("## Status: Tuning Required [WARN]")
        lines.append("")
        lines.append("Some KPI targets not met. Apply recommendations below before production freeze.")
        lines.append("")
        lines.append("### Required Changes (High Priority)")
        lines.append("")
        
        # Add specific recommendations for failed goals
        for goal_key, goal_met in goals.items():
            if not goal_met:
                lines.append(f"**{goal_key}:** Not met - see specific recommendations below")
        
        lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append("## Implementation Notes")
    lines.append("")
    lines.append("1. **Apply deltas incrementally** - Test each change in isolation")
    lines.append("2. **Run 12-24 iterations** after each change to validate")
    lines.append("3. **Monitor all KPIs** - Ensure no regressions")
    lines.append("4. **Use delta verifier** - Confirm 95%+ apply ratio")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Generated by soak build_reports at {timestamp}*")
    
    return '\n'.join(lines)


def generate_failures_md(data: Dict[str, Any], timestamp: str) -> str:
    """Generate FAILURES.md."""
    goals = data['goals']
    
    lines = []
    
    # Header
    lines.append("# Soak Test Failures Report")
    lines.append("")
    lines.append(f"**Generated:** {timestamp}")
    lines.append(f"**Status:** {'NO FAILURES' if all(goals.values()) else 'FAILURES DETECTED'}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    if all(goals.values()):
        lines.append("## Summary: No Failures [OK]")
        lines.append("")
        lines.append("All KPI targets met. No critical failures detected.")
        lines.append("")
        lines.append("**Metrics Passed:**")
        for goal, status in goals.items():
            lines.append(f"- {goal}: [OK]")
        lines.append("")
    else:
        lines.append("## Summary: KPI Targets Not Met [WARN]")
        lines.append("")
        lines.append("The following KPI targets were not achieved:")
        lines.append("")
        for goal, status in goals.items():
            status_str = "[OK]" if status else "[FAIL]"
            lines.append(f"- {goal}: {status_str}")
        lines.append("")
        lines.append("**Action Required:** Review RECOMMENDATIONS.md for remediation steps.")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append(f"*Generated by soak build_reports at {timestamp}*")
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate soak test analysis reports",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--src",
        type=str,
        required=True,
        help="Source directory containing ITER_SUMMARY_*.json files"
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output directory for generated reports"
    )
    parser.add_argument(
        "--last-n",
        type=int,
        default=8,
        help="Number of last iterations to analyze (default: 8)"
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    src_dir = Path(args.src).resolve()
    out_dir = Path(args.out).resolve()
    
    # Find soak directory (handle both "latest" and "latest 1" structures)
    if (src_dir / "soak" / "latest").exists():
        soak_dir = src_dir / "soak" / "latest"
    elif (src_dir / "latest").exists():
        soak_dir = src_dir / "latest"
    else:
        soak_dir = src_dir
    
    print("=" * 80)
    print("SOAK REPORT BUILDER")
    print("=" * 80)
    print(f"Source:  {soak_dir}")
    print(f"Output:  {out_dir}")
    print(f"Last-N:  {args.last_n}")
    print()
    
    # Load data
    print("[1/6] Loading iteration summaries...")
    summaries = load_iter_summaries(soak_dir)
    
    if not summaries:
        print("[ERROR] No ITER_SUMMARY files found", file=sys.stderr)
        return 1
    
    print(f"  Loaded {len(summaries)} iterations")
    
    # Extract metrics
    print("[2/6] Extracting metrics...")
    all_metrics = extract_kpi_metrics(summaries)
    all_stats = {k: calc_stats(v) for k, v in all_metrics.items()}
    
    # Analyze last N
    print(f"[3/6] Analyzing last-{args.last_n} iterations...")
    last_n = analyze_last_n(summaries, n=args.last_n)
    
    # Extract tuning & guards
    print("[4/6] Extracting tuning & guard info...")
    tuning_info = extract_tuning_info(summaries)
    guards_info = extract_guards_info(summaries)
    
    # Check goals
    print("[5/6] Checking goals...")
    goals = check_goals(last_n)
    
    # Prepare data
    timestamp = datetime.now(timezone.utc).isoformat()
    data = {
        'summaries': summaries,
        'all_metrics': all_metrics,
        'all_stats': all_stats,
        'last_n': last_n,
        'tuning_info': tuning_info,
        'guards_info': guards_info,
        'goals': goals,
    }
    
    # Create output directory
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate reports
    print("[6/6] Generating reports...")
    
    snapshot = generate_snapshot(data, timestamp)
    snapshot_path = out_dir / "POST_SOAK_SNAPSHOT.json"
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, indent=2)
    print(f"  Written: {snapshot_path}")
    
    audit_md = generate_audit_md(data, timestamp)
    audit_path = out_dir / "POST_SOAK_AUDIT.md"
    with open(audit_path, 'w', encoding='utf-8') as f:
        f.write(audit_md)
    print(f"  Written: {audit_path}")
    
    recommendations_md = generate_recommendations_md(data, timestamp)
    recommendations_path = out_dir / "RECOMMENDATIONS.md"
    with open(recommendations_path, 'w', encoding='utf-8') as f:
        f.write(recommendations_md)
    print(f"  Written: {recommendations_path}")
    
    failures_md = generate_failures_md(data, timestamp)
    failures_path = out_dir / "FAILURES.md"
    with open(failures_path, 'w', encoding='utf-8') as f:
        f.write(failures_md)
    print(f"  Written: {failures_path}")
    
    print()
    print("=" * 80)
    print("REPORTS GENERATED SUCCESSFULLY")
    print("=" * 80)
    print()
    
    # Final verdict
    verdict = snapshot['verdict']
    if verdict == 'PASS':
        print("[OK] All goals met - READY FOR PROD-FREEZE")
        return 0
    elif verdict == 'WARN':
        print("[WARN] Minor issues - Review recommendations")
        return 0
    else:
        print("[FAIL] Critical issues - Tuning required before freeze")
        return 1


if __name__ == '__main__':
    sys.exit(main())


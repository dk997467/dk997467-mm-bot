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

# Import EdgeSentinel for profile support
try:
    from strategy.edge_sentinel import EdgeSentinel
except ImportError:
    EdgeSentinel = None


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


# ==============================================================================
# AUTO-TUNING: Runtime Profile Adjustment
# ==============================================================================

def load_edge_report(path: str = "artifacts/reports/EDGE_REPORT.json") -> Dict[str, Any]:
    """
    Load extended EDGE_REPORT.json.
    
    Returns:
        EDGE_REPORT data dict (or empty if not found)
    """
    report_path = Path(path)
    if not report_path.exists():
        return {}
    
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def compute_tuning_adjustments(
    edge_report: Dict[str, Any],
    current_overrides: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[str], bool]:
    """
    Compute tuning adjustments based on EDGE_REPORT metrics.
    
    Returns:
        (new_overrides, reasons, multi_fail_guard_triggered)
    """
    totals = edge_report.get("totals", {})
    new_overrides = current_overrides.copy()
    reasons = []
    fail_count = 0
    
    # Get runtime limits from EdgeSentinel
    LIMITS = {
        "min_interval_ms": (50, 300),
        "replace_rate_per_min": (120, 360),
        "base_spread_bps_delta": (0.0, 0.6),
        "impact_cap_ratio": (0.04, 0.12),
        "tail_age_ms": (400, 1000),
    }
    
    # Track field change counts for max-2-changes guard
    field_changes = {}
    
    def apply_adjustment(field: str, delta: float, reason: str):
        """Apply adjustment with limits and tracking."""
        nonlocal new_overrides, field_changes, reasons
        
        # Track changes per field
        if field not in field_changes:
            field_changes[field] = 0
        
        # Guard: max 2 changes per field per iteration
        if field_changes[field] >= 2:
            return False
        
        # Get current value (or 0 for delta fields)
        current = new_overrides.get(field, 0.0 if "_delta" in field else 50)
        new_value = current + delta
        
        # Enforce limits
        if field in LIMITS:
            min_val, max_val = LIMITS[field]
            new_value = max(min_val, min(max_val, new_value))
        
        # Apply if changed
        if new_value != current:
            new_overrides[field] = new_value
            field_changes[field] += 1
            reasons.append(reason)
            return True
        
        return False
    
    # Trigger 1: cancel_ratio > 0.55
    cancel_ratio = totals.get("cancel_ratio", 0.0)
    if cancel_ratio > 0.55:
        fail_count += 1
        apply_adjustment("min_interval_ms", 20, "cancel_ratio>0.55")
        apply_adjustment("replace_rate_per_min", -30, "cancel_ratio>0.55")
    
    # Trigger 2: adverse_bps_p95 > 4 or slippage_bps_p95 > 3
    adverse = totals.get("adverse_bps_p95", 0.0)
    slippage = totals.get("slippage_bps_p95", 0.0)
    if adverse > 4.0 or slippage > 3.0:
        fail_count += 1
        apply_adjustment("base_spread_bps_delta", 0.05, "adverse/slippage>threshold")
    
    # Trigger 3: order_age_p95_ms > 330
    order_age = totals.get("order_age_p95_ms", 0.0)
    if order_age > 330:
        fail_count += 1
        apply_adjustment("replace_rate_per_min", -30, "order_age>330")
        apply_adjustment("tail_age_ms", 50, "order_age>330")
    
    # Trigger 4: ws_lag_p95_ms > 120
    ws_lag = totals.get("ws_lag_p95_ms", 0.0)
    if ws_lag > 120:
        fail_count += 1
        apply_adjustment("min_interval_ms", 20, "ws_lag>120")
    
    # Trigger 5: net_bps < 2.5 (only if no other triggers)
    net_bps = totals.get("net_bps", 0.0)
    if net_bps < 2.5 and fail_count == 0:
        apply_adjustment("base_spread_bps_delta", 0.02, "net_bps<2.5")
    
    # Multi-fail guard: if 3+ independent triggers, only calm down
    multi_fail_guard = fail_count >= 3
    if multi_fail_guard:
        # Override to only calming adjustments
        new_overrides = current_overrides.copy()
        reasons = ["multi_fail_guard"]
        
        # Only increase spread, min_interval, decrease replace_rate
        apply_adjustment("base_spread_bps_delta", 0.05, "multi_fail_guard")
        apply_adjustment("min_interval_ms", 20, "multi_fail_guard")
        apply_adjustment("replace_rate_per_min", -30, "multi_fail_guard")
    
    # Guard: max total spread_delta adjustment per iteration <= 0.1
    spread_delta_key = "base_spread_bps_delta"
    if spread_delta_key in new_overrides and spread_delta_key in current_overrides:
        delta_change = new_overrides[spread_delta_key] - current_overrides[spread_delta_key]
        if delta_change > 0.1:
            new_overrides[spread_delta_key] = current_overrides[spread_delta_key] + 0.1
            reasons.append("spread_delta_capped_at_0.1")
    
    return new_overrides, reasons, multi_fail_guard


def save_runtime_overrides(overrides: Dict[str, Any], path: str = "artifacts/soak/runtime_overrides.json"):
    """Save runtime overrides to file."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(overrides, f, sort_keys=True, separators=(',', ':'), indent=2)


def get_default_best_cell_overrides() -> Dict[str, Any]:
    """
    Return default runtime overrides from best parameter sweep cell.
    
    These values represent the best-performing configuration from parameter sweep,
    used as starting point for soak tests when no explicit overrides are provided.
    """
    return {
        "min_interval_ms": 60,
        "replace_rate_per_min": 300,
        "base_spread_bps_delta": 0.05,
        "tail_age_ms": 600,
        "impact_cap_ratio": 0.10,
        "max_delta_ratio": 0.15
    }


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Soak test runner and reporter")
    parser.add_argument("--hours", type=int, default=72, help="Soak duration in hours")
    parser.add_argument("--iterations", type=int, help="Number of iterations (mini-soak mode)")
    parser.add_argument("--export-json", type=str, help="Export JSON report path")
    parser.add_argument("--export-md", type=str, help="Export markdown report path")
    parser.add_argument("--gate-summary", type=str, help="Export gates summary JSON path")
    parser.add_argument("--mock", action="store_true", help="Use mock data for testing")
    parser.add_argument("--auto-tune", action="store_true", help="Enable runtime auto-tuning between iterations")
    args = parser.parse_args(argv)
    
    # Check for MM_PROFILE env var and load profile
    profile_name = os.environ.get("MM_PROFILE")
    sentinel = None
    
    if profile_name and EdgeSentinel:
        print(f"[INFO] Loading profile: {profile_name}")
        try:
            sentinel = EdgeSentinel(profile_name=profile_name)
            sentinel.save_applied_profile()
            print(f"[INFO] Profile {profile_name} applied successfully")
        except Exception as e:
            print(f"[WARN] Failed to load profile {profile_name}: {e}")
            sentinel = None
    
    # Mini-soak mode with auto-tuning
    if args.iterations and args.auto_tune:
        print(f"[INFO] Running mini-soak with auto-tuning: {args.iterations} iterations")
        
        # Initialize runtime overrides from best cell if not already present
        overrides_path = Path("artifacts/soak/runtime_overrides.json")
        env_overrides = os.environ.get("MM_RUNTIME_OVERRIDES_JSON")
        
        if env_overrides:
            # Env var takes precedence
            current_overrides = json.loads(env_overrides)
            print(f"| overrides | OK | source=env |")
        elif overrides_path.exists():
            # Load existing file
            with open(overrides_path, 'r', encoding='utf-8') as f:
                current_overrides = json.load(f)
            print(f"| overrides | OK | source=file |")
        else:
            # Use default best cell values
            current_overrides = get_default_best_cell_overrides()
            save_runtime_overrides(current_overrides)
            print(f"| overrides | OK | source=default_best_cell |")
        
        # Iterate with auto-tuning
        for iteration in range(args.iterations):
            print(f"\n{'='*60}")
            print(f"[ITER {iteration + 1}/{args.iterations}] Starting iteration")
            print(f"{'='*60}")
            
            # Save current overrides for this iteration
            if current_overrides:
                save_runtime_overrides(current_overrides)
                
                # Reload sentinel with new overrides
                if sentinel:
                    sentinel.load_runtime_overrides()
                    sentinel.save_applied_profile()
            
            # Simulate iteration (in real scenario, run strategy here)
            # For testing, generate mock EDGE_REPORT
            if args.mock:
                # Generate problematic metrics at first, then improve
                # This ensures auto-tuning logic is triggered
                if iteration == 0:
                    # First iteration: problematic metrics
                    mock_edge_report = {
                        "totals": {
                            "net_bps": 2.2,  # Low
                            "adverse_bps_p95": 5.0,  # High
                            "slippage_bps_p95": 3.5,  # High
                            "cancel_ratio": 0.60,  # High
                            "order_age_p95_ms": 340,  # High
                            "ws_lag_p95_ms": 130,  # High
                            "maker_share_pct": 88.0
                        },
                        "symbols": {},
                        "runtime": {"utc": "2025-10-12T12:00:00Z", "version": "test"}
                    }
                else:
                    # Subsequent iterations: metrics improve
                    mock_edge_report = {
                        "totals": {
                            "net_bps": 2.8 + (iteration * 0.1),
                            "adverse_bps_p95": 3.5 - (iteration * 0.2),
                            "slippage_bps_p95": 2.5 - (iteration * 0.15),
                            "cancel_ratio": 0.48 - (iteration * 0.05),
                            "order_age_p95_ms": 320 - (iteration * 10),
                            "ws_lag_p95_ms": 95 + (iteration * 5),
                            "maker_share_pct": 90.0 + (iteration * 0.5)
                        },
                        "symbols": {},
                        "runtime": {"utc": "2025-10-12T12:00:00Z", "version": "test"}
                    }
                # Save mock EDGE_REPORT
                edge_report_path = Path("artifacts/reports/EDGE_REPORT.json")
                edge_report_path.parent.mkdir(parents=True, exist_ok=True)
                with open(edge_report_path, 'w') as f:
                    json.dump(mock_edge_report, f, indent=2)
            
            # Load EDGE_REPORT from previous iteration
            edge_report = load_edge_report()
            
            if edge_report:
                # Compute tuning adjustments
                new_overrides, reasons, multi_fail_guard = compute_tuning_adjustments(
                    edge_report, current_overrides
                )
                
                # Print tuning results
                totals = edge_report.get("totals", {})
                adjustments_count = len([r for r in reasons if r != "multi_fail_guard"])
                
                if multi_fail_guard:
                    print("| soak_iter_tune | SKIP | REASON=multi_fail_guard |")
                elif adjustments_count > 0:
                    print(f"| soak_iter_tune | OK | ADJUSTMENTS={adjustments_count} " +
                          f"net_bps={totals.get('net_bps', 0):.2f} " +
                          f"cancel={totals.get('cancel_ratio', 0):.2f} " +
                          f"age_p95={totals.get('order_age_p95_ms', 0):.0f} " +
                          f"lag_p95={totals.get('ws_lag_p95_ms', 0):.0f} |")
                    
                    # Log individual reasons
                    for reason in reasons:
                        if reason != "multi_fail_guard":
                            print(f"  - {reason}")
                else:
                    print("| soak_iter_tune | OK | ADJUSTMENTS=0 metrics_stable |")
                
                # Update overrides for next iteration
                current_overrides = new_overrides
            else:
                print("[WARN] No EDGE_REPORT found, skipping auto-tuning for this iteration")
        
        # After all iterations, print summary
        print(f"\n{'='*60}")
        print(f"[MINI-SOAK COMPLETE] {args.iterations} iterations with auto-tuning")
        print(f"{'='*60}")
        print(f"Final overrides: {json.dumps(current_overrides, indent=2)}")
        print(f"{'='*60}\n")
        
        return 0
    
    # Mini-soak mode (for testing with iterations, no auto-tune)
    if args.iterations:
        print(f"[INFO] Running mini-soak: {args.iterations} iterations")
        
        # Apply default best cell overrides if not already present
        overrides_path = Path("artifacts/soak/runtime_overrides.json")
        env_overrides = os.environ.get("MM_RUNTIME_OVERRIDES_JSON")
        
        if env_overrides:
            current_overrides = json.loads(env_overrides)
            save_runtime_overrides(current_overrides)
            print(f"| overrides | OK | source=env |")
        elif overrides_path.exists():
            print(f"| overrides | OK | source=file_existing |")
        else:
            current_overrides = get_default_best_cell_overrides()
            save_runtime_overrides(current_overrides)
            print(f"| overrides | OK | source=default_best_cell |")
        
        # Reload sentinel with overrides
        if sentinel:
            sentinel.load_runtime_overrides()
            sentinel.save_applied_profile()
        
        duration_hours = 0  # Mini-soak doesn't track hours
    else:
        duration_hours = args.hours
    
    # Collect metrics
    metrics = collect_metrics(duration_hours, mock=args.mock)
    
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


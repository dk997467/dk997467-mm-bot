#!/usr/bin/env python3
"""
F1 precheck script - validates D2 and E2 reports for deployment readiness.
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional


def parse_utc_timestamp(timestamp_str: str) -> datetime:
    """Parse UTC timestamp from ISO format."""
    try:
        # Handle both with and without 'Z' suffix
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1] + '+00:00'
        return datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}") from e


def check_report_age(report_path: str, max_age_hours: float) -> tuple[bool, str]:
    """Check if report is within acceptable age limit."""
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        
        # Look for timestamp in various possible locations
        timestamp_str = None
        
        # Try metadata.generated_at or similar
        metadata = report.get("metadata", {})
        if "generated_at_utc" in metadata:
            timestamp_str = metadata["generated_at_utc"]
        elif "timestamp_utc" in metadata:
            timestamp_str = metadata["timestamp_utc"]
        elif "generated_at" in metadata:
            timestamp_str = metadata["generated_at"]
        
        if not timestamp_str:
            return False, "No timestamp found in report metadata"
        
        report_time = parse_utc_timestamp(timestamp_str)
        now = datetime.now(timezone.utc)
        age_hours = (now - report_time).total_seconds() / 3600
        
        if age_hours > max_age_hours:
            return False, f"Report too old: {age_hours:.1f}h > {max_age_hours}h"
        
        return True, f"Report age: {age_hours:.1f}h"
        
    except Exception as e:
        return False, f"Failed to check report age: {e}"


def check_d2_gates(wf_report_path: str) -> tuple[bool, List[str]]:
    """Check D2 walk-forward tuning gates."""
    try:
        with open(wf_report_path, 'r', encoding='utf-8') as f:
            wf_report = json.load(f)
        
        reasons = []
        passed = True
        
        # Check if gates passed (or equivalent flag)
        gates_info = wf_report.get("gates", {})
        if not gates_info:
            # Look for alternative structure
            if "champion" in wf_report:
                champion = wf_report["champion"]
                # Check basic metrics exist
                if "hit_rate" not in champion or "maker_share" not in champion:
                    passed = False
                    reasons.append("Missing champion metrics (hit_rate, maker_share)")
            else:
                passed = False
                reasons.append("No gates or champion information found")
        else:
            gates_passed = gates_info.get("passed", False)
            if not gates_passed:
                passed = False
                gate_reasons = gates_info.get("reasons", ["Unknown gate failures"])
                reasons.extend([f"D2 gate: {reason}" for reason in gate_reasons])
        
        return passed, reasons
        
    except Exception as e:
        return False, [f"Failed to check D2 gates: {e}"]


def check_e2_divergence(calib_report_path: str, div_threshold: float) -> tuple[bool, List[str]]:
    """Check E2 sim-live divergence."""
    try:
        with open(calib_report_path, 'r', encoding='utf-8') as f:
            calib_report = json.load(f)
        
        reasons = []
        passed = True
        
        go_no_go = calib_report.get("go_no_go", {})
        if not go_no_go:
            passed = False
            reasons.append("Missing go_no_go block in E2 report")
            return passed, reasons
        
        divergence = go_no_go.get("sim_live_divergence")
        if divergence is None:
            passed = False
            reasons.append("Missing sim_live_divergence in go_no_go")
            return passed, reasons
        
        # Check against threshold
        if divergence > div_threshold:
            passed = False
            reasons.append(f"High sim-live divergence: {divergence:.3f} > {div_threshold}")
        
        # Warning for unusual values (outside typical range)
        if divergence < 0.05 or divergence > 0.20:
            reasons.append(f"WARNING: Divergence {divergence:.3f} outside typical range [0.05, 0.20]")
        
        return passed, reasons
        
    except Exception as e:
        return False, [f"Failed to check E2 divergence: {e}"]


def check_baseline_drift(wf_report_path: str, max_drift_pct: float, whitelist: List[str]) -> tuple[bool, List[str]]:
    """Check parameter drift against baseline."""
    try:
        with open(wf_report_path, 'r', encoding='utf-8') as f:
            wf_report = json.load(f)
        
        reasons = []
        passed = True
        
        # Look for baseline drift information
        drift_info = wf_report.get("baseline_drift", {})
        if not drift_info:
            # Not an error if baseline drift isn't calculated
            return True, ["No baseline drift data (acceptable)"]
        
        param_drift = drift_info.get("param_drift_pct", {})
        if not param_drift:
            return True, ["No parameter drift data (acceptable)"]
        
        # Check each whitelisted parameter
        for param in whitelist:
            if param in param_drift:
                drift_pct = abs(param_drift[param])  # Take absolute value
                if drift_pct > max_drift_pct:
                    passed = False
                    reasons.append(f"High parameter drift {param}: {drift_pct:.1f}% > {max_drift_pct}%")
        
        return passed, reasons
        
    except Exception as e:
        return False, [f"Failed to check baseline drift: {e}"]


def main():
    """F1 precheck main function."""
    parser = argparse.ArgumentParser(description="F1 deployment precheck")
    
    parser.add_argument("--wf-report", type=str, required=True,
                       help="D2 walk-forward report.json path")
    parser.add_argument("--calib-report", type=str, required=True,
                       help="E2 calibration report.json path")
    parser.add_argument("--max-age-hours", type=float, default=72,
                       help="Maximum report age in hours")
    parser.add_argument("--max-drift-pct", type=float, default=50.0,
                       help="Maximum parameter drift percentage")
    parser.add_argument("--div-threshold", type=float, default=0.15,
                       help="Maximum sim-live divergence threshold")
    parser.add_argument("--whitelist", type=str,
                       default="k_vola_spread,skew_coeff,levels_per_side,level_spacing_coeff,min_time_in_book_ms,replace_threshold_bps,imbalance_cutoff",
                       help="Comma-separated list of parameters to check for drift")
    
    args = parser.parse_args()
    
    # Parse whitelist
    whitelist_params = [param.strip() for param in args.whitelist.split(",") if param.strip()]
    
    # Initialize results
    all_passed = True
    all_reasons = []
    
    print("F1 Precheck Starting...")
    print(f"D2 Report: {args.wf_report}")
    print(f"E2 Report: {args.calib_report}")
    print()
    
    # Check D2 report age
    print("[CHECK] D2 report age...")
    d2_age_ok, d2_age_reason = check_report_age(args.wf_report, args.max_age_hours)
    if not d2_age_ok:
        all_passed = False
        all_reasons.append(f"D2 age: {d2_age_reason}")
    else:
        print(f"  OK: {d2_age_reason}")
    
    # Check E2 report age
    print("[CHECK] E2 report age...")
    e2_age_ok, e2_age_reason = check_report_age(args.calib_report, args.max_age_hours)
    if not e2_age_ok:
        all_passed = False
        all_reasons.append(f"E2 age: {e2_age_reason}")
    else:
        print(f"  OK: {e2_age_reason}")
    
    # Check D2 gates
    print("[CHECK] D2 walk-forward gates...")
    d2_gates_ok, d2_gate_reasons = check_d2_gates(args.wf_report)
    if not d2_gates_ok:
        all_passed = False
        all_reasons.extend(d2_gate_reasons)
    else:
        print("  OK: D2 gates passed")
    
    # Check E2 divergence
    print("[CHECK] E2 sim-live divergence...")
    e2_div_ok, e2_div_reasons = check_e2_divergence(args.calib_report, args.div_threshold)
    if not e2_div_ok:
        all_passed = False
        all_reasons.extend(e2_div_reasons)
    else:
        print(f"  OK: Divergence within threshold ({args.div_threshold})")
    
    # Check any warnings from E2
    for reason in e2_div_reasons:
        if reason.startswith("WARNING"):
            print(f"  {reason}")
    
    # Check baseline drift
    print("[CHECK] Parameter drift...")
    drift_ok, drift_reasons = check_baseline_drift(args.wf_report, args.max_drift_pct, whitelist_params)
    if not drift_ok:
        all_passed = False
        all_reasons.extend(drift_reasons)
    else:
        print(f"  OK: Parameter drift within {args.max_drift_pct}% threshold")
    
    # Final result
    print()
    result = "PASS" if all_passed else "FAIL"
    print(f"F1 precheck: {result}")
    
    if all_reasons:
        print()
        for reason in all_reasons:
            print(f"- reason: {reason}")
    
    # Exit with appropriate code
    if all_passed:
        sys.exit(0)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()

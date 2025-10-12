#!/usr/bin/env python3
"""
Readiness Validator & KPI Gate - CI Gate for Production Readiness

Validates readiness.json structure, ranges, and verdict.
Also acts as KPI Gate for EDGE_REPORT metrics with WARN/FAIL thresholds.

Usage:
    # Validate readiness.json
    python -m tools.ci.validate_readiness artifacts/reports/readiness.json
    
    # Run as KPI Gate
    python -m tools.ci.validate_readiness --kpi-gate --edge-report artifacts/reports/EDGE_REPORT.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def validate_structure(data: Dict[str, Any]) -> List[str]:
    """Validate JSON structure."""
    errors = []
    
    # Check required top-level keys
    required_keys = ["runtime", "score", "sections", "verdict"]
    for key in required_keys:
        if key not in data:
            errors.append(f"Missing required key: '{key}'")
    
    if errors:
        return errors
    
    # Validate runtime
    if not isinstance(data["runtime"], dict):
        errors.append("'runtime' must be a dict")
    else:
        if "utc" not in data["runtime"]:
            errors.append("Missing 'runtime.utc'")
        if "version" not in data["runtime"]:
            errors.append("Missing 'runtime.version'")
    
    # Validate score
    if not isinstance(data["score"], (int, float)):
        errors.append("'score' must be a number")
    
    # Validate sections
    if not isinstance(data["sections"], dict):
        errors.append("'sections' must be a dict")
    else:
        expected_sections = ["chaos", "edge", "guards", "latency", "taker", "tests"]
        for section in expected_sections:
            if section not in data["sections"]:
                errors.append(f"Missing section: '{section}'")
            elif not isinstance(data["sections"][section], (int, float)):
                errors.append(f"Section '{section}' must be a number")
    
    # Validate verdict
    if not isinstance(data["verdict"], str):
        errors.append("'verdict' must be a string")
    elif data["verdict"] not in ["GO", "HOLD"]:
        errors.append(f"'verdict' must be 'GO' or 'HOLD', got: '{data['verdict']}'")
    
    return errors


def validate_ranges(data: Dict[str, Any]) -> List[str]:
    """Validate value ranges."""
    errors = []
    
    # Score must be 0-100
    score = data.get("score", -1)
    if not (0 <= score <= 100):
        errors.append(f"'score' must be 0-100, got: {score}")
    
    # Sections must be 0-max
    sections = data.get("sections", {})
    max_scores = {
        "chaos": 10.0,
        "edge": 30.0,
        "guards": 10.0,
        "latency": 25.0,
        "taker": 15.0,
        "tests": 10.0
    }
    
    for section, max_score in max_scores.items():
        if section in sections:
            val = sections[section]
            if not (0 <= val <= max_score):
                errors.append(f"Section '{section}' must be 0-{max_score}, got: {val}")
    
    return errors


def validate_verdict(data: Dict[str, Any]) -> List[str]:
    """Validate verdict logic."""
    errors = []
    
    score = data.get("score", -1)
    verdict = data.get("verdict", "")
    
    # GO only if score == 100
    if verdict == "GO" and score != 100.0:
        errors.append(f"Verdict 'GO' requires score=100.0, got: {score}")
    
    # HOLD if score < 100
    if verdict == "HOLD" and score == 100.0:
        errors.append(f"Verdict 'HOLD' invalid for score=100.0")
    
    return errors


# ==============================================================================
# KPI GATE: Edge Metrics Thresholds
# ==============================================================================

class KPIThresholds:
    """Threshold configuration for KPI Gate."""
    
    def __init__(self):
        """Initialize thresholds from environment or defaults."""
        # Adverse selection (BPS, p95)
        self.adverse_bps_p95_warn = float(os.environ.get("KPI_ADVERSE_WARN", "4.0"))
        self.adverse_bps_p95_fail = float(os.environ.get("KPI_ADVERSE_FAIL", "6.0"))
        
        # Slippage (BPS, p95)
        self.slippage_bps_p95_warn = float(os.environ.get("KPI_SLIPPAGE_WARN", "3.0"))
        self.slippage_bps_p95_fail = float(os.environ.get("KPI_SLIPPAGE_FAIL", "5.0"))
        
        # Cancel ratio (fraction)
        self.cancel_ratio_warn = float(os.environ.get("KPI_CANCEL_WARN", "0.55"))
        self.cancel_ratio_fail = float(os.environ.get("KPI_CANCEL_FAIL", "0.70"))
        
        # Order age (milliseconds, p95)
        self.order_age_p95_ms_warn = float(os.environ.get("KPI_ORDER_AGE_WARN", "330"))
        self.order_age_p95_ms_fail = float(os.environ.get("KPI_ORDER_AGE_FAIL", "360"))
        
        # WebSocket lag (milliseconds, p95)
        self.ws_lag_p95_ms_warn = float(os.environ.get("KPI_WS_LAG_WARN", "120"))
        self.ws_lag_p95_ms_fail = float(os.environ.get("KPI_WS_LAG_FAIL", "180"))
        
        # Net BPS (total)
        self.net_bps_fail = float(os.environ.get("KPI_NET_BPS_FAIL", "2.5"))
        
        # Maker share (percentage)
        self.maker_share_pct_fail = float(os.environ.get("KPI_MAKER_SHARE_FAIL", "85.0"))


def check_kpi_thresholds(
    metrics: Dict[str, Any],
    thresholds: KPIThresholds
) -> Tuple[str, List[str]]:
    """
    Check metrics against KPI thresholds.
    
    Args:
        metrics: Extended EDGE_REPORT metrics
        thresholds: Threshold configuration
        
    Returns:
        Tuple of (verdict, reasons) where verdict is "OK", "WARN", or "FAIL"
    """
    totals = metrics.get("totals", {})
    reasons = []
    has_fail = False
    has_warn = False
    
    # Check adverse_bps_p95
    adverse = totals.get("adverse_bps_p95", 0.0)
    if adverse > thresholds.adverse_bps_p95_fail:
        reasons.append("EDGE:adverse")
        has_fail = True
    elif adverse > thresholds.adverse_bps_p95_warn:
        reasons.append("EDGE:adverse")
        has_warn = True
    
    # Check slippage_bps_p95
    slippage = totals.get("slippage_bps_p95", 0.0)
    if slippage > thresholds.slippage_bps_p95_fail:
        reasons.append("EDGE:slippage")
        has_fail = True
    elif slippage > thresholds.slippage_bps_p95_warn:
        reasons.append("EDGE:slippage")
        has_warn = True
    
    # Check cancel_ratio
    cancel_ratio = totals.get("cancel_ratio", 0.0)
    if cancel_ratio > thresholds.cancel_ratio_fail:
        reasons.append("EDGE:cancel_ratio")
        has_fail = True
    elif cancel_ratio > thresholds.cancel_ratio_warn:
        reasons.append("EDGE:cancel_ratio")
        has_warn = True
    
    # Check order_age_p95_ms
    order_age = totals.get("order_age_p95_ms", 0.0)
    if order_age > thresholds.order_age_p95_ms_fail:
        reasons.append("EDGE:order_age")
        has_fail = True
    elif order_age > thresholds.order_age_p95_ms_warn:
        reasons.append("EDGE:order_age")
        has_warn = True
    
    # Check ws_lag_p95_ms
    ws_lag = totals.get("ws_lag_p95_ms", 0.0)
    if ws_lag > thresholds.ws_lag_p95_ms_fail:
        reasons.append("EDGE:ws_lag")
        has_fail = True
    elif ws_lag > thresholds.ws_lag_p95_ms_warn:
        reasons.append("EDGE:ws_lag")
        has_warn = True
    
    # Check net_bps (FAIL only)
    net_bps = totals.get("net_bps", 0.0)
    if net_bps < thresholds.net_bps_fail:
        reasons.append("EDGE:net_bps")
        has_fail = True
    
    # Check maker_share_pct (FAIL only)
    maker_share = totals.get("maker_share_pct", 0.0)
    if maker_share < thresholds.maker_share_pct_fail:
        reasons.append("EDGE:maker_share")
        has_fail = True
    
    # Determine verdict
    if has_fail:
        verdict = "FAIL"
    elif has_warn:
        verdict = "WARN"
    else:
        verdict = "OK"
    
    return verdict, reasons


def run_kpi_gate(edge_report_path: str, output_path: Optional[str] = None) -> int:
    """
    Run KPI Gate on EDGE_REPORT.json.
    
    Args:
        edge_report_path: Path to EDGE_REPORT.json
        output_path: Path to write KPI_GATE.json (optional)
        
    Returns:
        Exit code (0 for OK, 1 for WARN/FAIL)
    """
    # Load EDGE_REPORT
    edge_path = Path(edge_report_path)
    if not edge_path.exists():
        print(f"[ERROR] EDGE_REPORT not found: {edge_path}", file=sys.stderr)
        return 1
    
    try:
        with open(edge_path, 'r') as f:
            metrics = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid EDGE_REPORT JSON: {e}", file=sys.stderr)
        return 1
    
    # Load thresholds
    thresholds = KPIThresholds()
    
    # Check thresholds
    verdict, reasons = check_kpi_thresholds(metrics, thresholds)
    
    # Get runtime info
    if 'MM_FREEZE_UTC_ISO' in os.environ:
        utc = os.environ['MM_FREEZE_UTC_ISO']
    else:
        utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    version = os.environ.get('MM_VERSION', 'dev')
    
    # Build result
    result = {
        "verdict": verdict,
        "reasons": reasons,
        "runtime": {
            "utc": utc,
            "version": version
        }
    }
    
    # Write output JSON
    if output_path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        json_output = json.dumps(result, sort_keys=True, separators=(',', ':'))
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(json_output + '\n')
        
        print(f"[INFO] KPI_GATE.json written to {output_file}", file=sys.stderr)
    
    # Print marker for CI/CD
    if verdict == "OK":
        print("| kpi_gate | OK | THRESHOLDS=APPLIED |")
    elif verdict == "WARN":
        reasons_str = ','.join(reasons)
        print(f"| kpi_gate | WARN | REASONS={reasons_str} |")
    else:  # FAIL
        reasons_str = ','.join(reasons)
        print(f"| kpi_gate | FAIL | REASONS={reasons_str} |")
    
    # Report summary
    totals = metrics.get("totals", {})
    print(f"\n[KPI GATE] Verdict: {verdict}", file=sys.stderr)
    if reasons:
        print(f"[KPI GATE] Reasons: {', '.join(reasons)}", file=sys.stderr)
    print(f"[KPI GATE] Metrics:", file=sys.stderr)
    print(f"  - net_bps: {totals.get('net_bps', 0.0):.2f}", file=sys.stderr)
    print(f"  - adverse_bps_p95: {totals.get('adverse_bps_p95', 0.0):.2f}", file=sys.stderr)
    print(f"  - slippage_bps_p95: {totals.get('slippage_bps_p95', 0.0):.2f}", file=sys.stderr)
    print(f"  - cancel_ratio: {totals.get('cancel_ratio', 0.0):.2%}", file=sys.stderr)
    print(f"  - maker_share_pct: {totals.get('maker_share_pct', 0.0):.1f}%", file=sys.stderr)
    
    # Exit code: 0 for OK, 1 for WARN/FAIL
    return 0 if verdict == "OK" else 1


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate readiness JSON or run KPI Gate")
    
    # Mode selection
    parser.add_argument(
        "--kpi-gate",
        action="store_true",
        help="Run as KPI Gate (check EDGE_REPORT thresholds)"
    )
    
    # Readiness mode
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to readiness.json (required if not using --kpi-gate)"
    )
    
    # KPI Gate mode
    parser.add_argument(
        "--edge-report",
        type=str,
        default="artifacts/reports/EDGE_REPORT.json",
        help="Path to EDGE_REPORT.json (default: artifacts/reports/EDGE_REPORT.json)"
    )
    
    parser.add_argument(
        "--out-json",
        type=str,
        default="artifacts/reports/KPI_GATE.json",
        help="Output path for KPI_GATE.json (default: artifacts/reports/KPI_GATE.json)"
    )
    
    args = parser.parse_args(argv)
    
    # KPI Gate mode
    if args.kpi_gate:
        return run_kpi_gate(args.edge_report, args.out_json)
    
    # Readiness validation mode (legacy)
    if not args.file:
        print("[ERROR] file argument required (or use --kpi-gate)", file=sys.stderr)
        parser.print_help()
        return 1
    
    # Check file exists
    if not Path(args.file).exists():
        print(f"[ERROR] File not found: {args.file}", file=sys.stderr)
        return 1
    
    # Load JSON
    try:
        with open(args.file, 'r') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON: {e}", file=sys.stderr)
        return 1
    
    # Validate
    all_errors = []
    all_errors.extend(validate_structure(data))
    
    if not all_errors:  # Only validate ranges/verdict if structure is OK
        all_errors.extend(validate_ranges(data))
        all_errors.extend(validate_verdict(data))
    
    # Report
    if all_errors:
        print(f"[VALIDATION FAILED] {len(all_errors)} error(s):")
        for err in all_errors:
            print(f"  - {err}")
        return 1
    
    # Check verdict
    verdict = data["verdict"]
    score = data["score"]
    
    if verdict == "GO":
        print(f"[PASS] Readiness: GO (score={score})")
        return 0
    else:
        print(f"[FAIL] Readiness: HOLD (score={score})")
        print("[INFO] Production deployment blocked")
        return 1


if __name__ == "__main__":
    sys.exit(main())


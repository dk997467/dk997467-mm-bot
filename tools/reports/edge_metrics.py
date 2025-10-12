#!/usr/bin/env python3
"""
Edge Metrics Calculator - Compute extended edge metrics from artifacts

Computes detailed edge performance metrics from EDGE_REPORT.json, audit logs,
and strategy metrics. Provides stdlib-only, deterministic output.

Usage:
    from tools.reports.edge_metrics import compute_edge_metrics, load_edge_inputs
    
    inputs = load_edge_inputs(edge_report_path="artifacts/EDGE_REPORT.json")
    metrics = compute_edge_metrics(inputs)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_runtime_info(version: Optional[str] = None) -> Dict[str, str]:
    """Get runtime info (UTC timestamp + version)."""
    # Respect MM_FREEZE_UTC_ISO for deterministic testing
    if 'MM_FREEZE_UTC_ISO' in os.environ:
        utc = os.environ['MM_FREEZE_UTC_ISO']
    else:
        utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    if version is None:
        version = os.environ.get('MM_VERSION', 'dev')
    
    return {"utc": utc, "version": version}


def load_json_safe(path: Path) -> Dict[str, Any]:
    """Load JSON file safely, return empty dict if missing."""
    if not path.exists():
        return {}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def calculate_percentile(values: List[float], percentile: float) -> float:
    """Calculate percentile (0.0-1.0) from list of values."""
    if not values:
        return 0.0
    
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * percentile)
    idx = min(idx, len(sorted_vals) - 1)
    
    return sorted_vals[idx]


def load_edge_inputs(
    edge_report_path: Optional[str] = None,
    audit_path: Optional[str] = None,
    metrics_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Load edge inputs from various artifacts.
    
    Args:
        edge_report_path: Path to EDGE_REPORT.json (default: artifacts/EDGE_REPORT.json)
        audit_path: Path to audit.jsonl (optional)
        metrics_path: Path to strategy metrics (optional)
        
    Returns:
        Dict with loaded data from each source
    """
    # Find workspace root
    current_file = Path(__file__).resolve()
    workspace_root = current_file.parents[2]  # tools/reports -> tools -> root
    
    # Default paths
    if edge_report_path is None:
        edge_report_path = workspace_root / "artifacts" / "EDGE_REPORT.json"
    else:
        edge_report_path = Path(edge_report_path)
    
    # Load data
    edge_report = load_json_safe(edge_report_path)
    
    # Audit and metrics are optional
    audit_data = []
    if audit_path:
        audit_path = Path(audit_path)
        if audit_path.exists():
            try:
                with open(audit_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            audit_data.append(json.loads(line))
            except Exception:
                pass
    
    metrics_data = {}
    if metrics_path:
        metrics_data = load_json_safe(Path(metrics_path))
    
    return {
        "edge_report": edge_report,
        "audit": audit_data,
        "metrics": metrics_data,
    }


def compute_edge_metrics(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute extended edge metrics from inputs.
    
    Args:
        inputs: Dict from load_edge_inputs()
        
    Returns:
        Dict with extended metrics structure:
        {
            "totals": {
                "net_bps": float,
                "gross_bps": float,
                "adverse_bps_p95": float,
                "slippage_bps_p95": float,
                "fees_eff_bps": float,
                "inventory_bps": float,
                "order_age_p95_ms": float,
                "ws_lag_p95_ms": float,
                "replace_ratio": float,
                "cancel_ratio": float,
                "blocked_ratio": {...},
                "maker_share_pct": float
            },
            "symbols": {...},
            "runtime": {...}
        }
    """
    edge_report = inputs.get("edge_report", {})
    audit_data = inputs.get("audit", [])
    
    # Extract base metrics from existing EDGE_REPORT
    totals = edge_report.get("total", {})
    
    # Compute extended metrics
    extended_totals = {
        # Core metrics (from existing report)
        "net_bps": totals.get("net_bps", 0.0),
        "gross_bps": totals.get("gross_bps", 0.0),
        "fees_eff_bps": totals.get("fees_bps", 0.0),
        "inventory_bps": totals.get("inventory_bps", 0.0),
        
        # P95 metrics (compute from distributions if available)
        "adverse_bps_p95": compute_p95_metric(totals, "adverse_bps"),
        "slippage_bps_p95": compute_p95_metric(totals, "slippage_bps"),
        "order_age_p95_ms": compute_p95_metric(totals, "order_age_ms"),
        "ws_lag_p95_ms": compute_p95_metric(totals, "ws_lag_ms"),
        
        # Ratio metrics (from audit data if available)
        "replace_ratio": compute_replace_ratio(audit_data),
        "cancel_ratio": compute_cancel_ratio(audit_data),
        
        # Blocked ratios (from audit data or edge report)
        "blocked_ratio": compute_blocked_ratios(audit_data, totals),
        
        # Maker share
        "maker_share_pct": totals.get("maker_share", 0.0) * 100.0,
    }
    
    # Compute per-symbol metrics (optional)
    symbols_data = {}
    symbols = edge_report.get("symbols", {})
    for symbol, symbol_totals in symbols.items():
        symbols_data[symbol] = {
            "net_bps": symbol_totals.get("net_bps", 0.0),
            "gross_bps": symbol_totals.get("gross_bps", 0.0),
            "adverse_bps_p95": compute_p95_metric(symbol_totals, "adverse_bps"),
            "slippage_bps_p95": compute_p95_metric(symbol_totals, "slippage_bps"),
            "maker_share_pct": symbol_totals.get("maker_share", 0.0) * 100.0,
        }
    
    return {
        "totals": extended_totals,
        "symbols": symbols_data,
        "runtime": get_runtime_info(),
    }


def compute_p95_metric(data: Dict[str, Any], metric_name: str) -> float:
    """
    Compute P95 value for a metric.
    
    Looks for distributions (e.g., 'adverse_bps_dist') or falls back to mean/max.
    """
    # Check for distribution data
    dist_key = f"{metric_name}_dist"
    if dist_key in data and isinstance(data[dist_key], list):
        return calculate_percentile(data[dist_key], 0.95)
    
    # Check for p95 key directly
    p95_key = f"{metric_name}_p95"
    if p95_key in data:
        return data[p95_key]
    
    # Fallback: use max or mean
    max_key = f"{metric_name}_max"
    if max_key in data:
        return data[max_key]
    
    # Last fallback: use the metric itself
    if metric_name in data:
        return data[metric_name]
    
    return 0.0


def compute_replace_ratio(audit_data: List[Dict[str, Any]]) -> float:
    """
    Compute replace ratio from audit data.
    
    replace_ratio = REPLACE / (PLACE + REPLACE + CANCEL)
    """
    if not audit_data:
        return 0.0
    
    replace_count = sum(1 for entry in audit_data if entry.get("action") == "REPLACE")
    place_count = sum(1 for entry in audit_data if entry.get("action") == "PLACE")
    cancel_count = sum(1 for entry in audit_data if entry.get("action") == "CANCEL")
    
    total = place_count + replace_count + cancel_count
    if total == 0:
        return 0.0
    
    return replace_count / total


def compute_cancel_ratio(audit_data: List[Dict[str, Any]]) -> float:
    """
    Compute cancel ratio from audit data.
    
    cancel_ratio = CANCEL / (PLACE + REPLACE + CANCEL)
    """
    if not audit_data:
        return 0.0
    
    place_count = sum(1 for entry in audit_data if entry.get("action") == "PLACE")
    replace_count = sum(1 for entry in audit_data if entry.get("action") == "REPLACE")
    cancel_count = sum(1 for entry in audit_data if entry.get("action") == "CANCEL")
    
    total = place_count + replace_count + cancel_count
    if total == 0:
        return 0.0
    
    return cancel_count / total


def compute_blocked_ratios(
    audit_data: List[Dict[str, Any]],
    totals: Dict[str, Any]
) -> Dict[str, float]:
    """
    Compute blocked ratios from audit data or edge report.
    
    Returns dict with keys: min_interval, concurrency, risk, throttle
    """
    # Try to extract from audit data
    if audit_data:
        blocked_counts = {
            "min_interval": sum(1 for e in audit_data if e.get("blocked_reason") == "min_interval"),
            "concurrency": sum(1 for e in audit_data if e.get("blocked_reason") == "concurrency"),
            "risk": sum(1 for e in audit_data if e.get("blocked_reason") == "risk"),
            "throttle": sum(1 for e in audit_data if e.get("blocked_reason") == "throttle"),
        }
        
        total_blocked = sum(blocked_counts.values())
        if total_blocked > 0:
            return {k: v / total_blocked for k, v in blocked_counts.items()}
    
    # Fallback: check if edge report has blocked_by field
    if "blocked_by" in totals:
        blocked_by = totals["blocked_by"]
        return {
            "min_interval": blocked_by.get("min_interval", 0.0),
            "concurrency": blocked_by.get("concurrency", 0.0),
            "risk": blocked_by.get("risk", 0.0),
            "throttle": blocked_by.get("throttle", 0.0),
        }
    
    # Default: all zeros
    return {
        "min_interval": 0.0,
        "concurrency": 0.0,
        "risk": 0.0,
        "throttle": 0.0,
    }


def main():
    """CLI entry point for testing."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Compute edge metrics from artifacts")
    parser.add_argument(
        "--edge-report",
        type=str,
        help="Path to EDGE_REPORT.json (default: artifacts/EDGE_REPORT.json)"
    )
    parser.add_argument(
        "--audit",
        type=str,
        help="Path to audit.jsonl (optional)"
    )
    parser.add_argument(
        "--out-json",
        type=str,
        help="Output path for metrics JSON (default: stdout)"
    )
    
    args = parser.parse_args()
    
    # Load inputs
    inputs = load_edge_inputs(
        edge_report_path=args.edge_report,
        audit_path=args.audit
    )
    
    # Compute metrics
    metrics = compute_edge_metrics(inputs)
    
    # Format JSON (deterministic, compact)
    json_output = json.dumps(metrics, sort_keys=True, separators=(',', ':'))
    
    # Output
    if args.out_json:
        output_path = Path(args.out_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_output + '\n')
        print(f"[INFO] Edge metrics written to {output_path}")
    else:
        print(json_output)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())


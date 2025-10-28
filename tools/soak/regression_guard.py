#!/usr/bin/env python3
"""
Regression Guard: Detect performance regression between today and recent history.

Usage:
    from tools.soak.regression_guard import check
    result = check(today_report, last_7days_reports)
"""
from __future__ import annotations
from typing import Dict, Any, List
from pathlib import Path
import json
import argparse
import sys


def check(today: Dict[str, Any], history: List[Dict[str, Any]], threshold: float = 0.10) -> Dict[str, Any]:
    """
    Check for performance regression by comparing today's metrics to historical baseline.
    
    Args:
        today: Today's report dict with KPIs
        history: List of recent reports (e.g., last 7 days)
        threshold: Regression threshold (default: 0.10 = 10%)
    
    Returns:
        Dictionary with:
        {
            "ok": bool (False if regression detected),
            "reason": str ("NONE" | "EDGE_REG" | "LAT_REG" | "TAKER_REG"),
            "details": dict
        }
    
    Example:
        >>> today = {"edge_net_bps": 2.0, "order_age_p95_ms": 400, "taker_share_pct": 15}
        >>> history = [{"edge_net_bps": 3.0, "order_age_p95_ms": 300, "taker_share_pct": 12}]
        >>> result = check(today, history)
        >>> result['ok']
        False
        >>> result['reason']
        'EDGE_REG'
    """
    if not history:
        return {"ok": True, "reason": "NONE", "details": {}}
    
    # Calculate baseline from history (median or mean)
    def _avg(key: str) -> float:
        vals = [float(r.get(key, 0.0)) for r in history if key in r]
        return sum(vals) / len(vals) if vals else 0.0
    
    baseline = {
        "edge_net_bps": _avg("edge_net_bps"),
        "order_age_p95_ms": _avg("order_age_p95_ms"),
        "taker_share_pct": _avg("taker_share_pct"),
        "fill_rate": _avg("fill_rate")
    }
    
    # Compare today to baseline
    today_edge = float(today.get("edge_net_bps", 0.0))
    today_lat = float(today.get("order_age_p95_ms", 0.0))
    today_taker = float(today.get("taker_share_pct", 0.0))
    today_fill_rate = float(today.get("fill_rate", 0.0))
    
    base_edge = baseline["edge_net_bps"]
    base_lat = baseline["order_age_p95_ms"]
    base_taker = baseline["taker_share_pct"]
    base_fill_rate = baseline["fill_rate"]
    
    details = {
        "today": {
            "edge_net_bps": today_edge,
            "order_age_p95_ms": today_lat,
            "taker_share_pct": today_taker,
            "fill_rate": today_fill_rate
        },
        "baseline": baseline,
        "current": {
            "edge_net_bps": today_edge,
            "order_age_p95_ms": today_lat,
            "taker_share_pct": today_taker,
            "fill_rate": today_fill_rate
        }
    }
    
    # Check for regressions (higher is better for edge, lower is better for latency/taker)
    
    # EDGE regression: if today's edge is significantly worse than baseline
    if base_edge > 0 and today_edge < base_edge:
        rel_delta = abs(today_edge - base_edge) / base_edge
        if rel_delta > threshold:
            return {"ok": False, "reason": "EDGE_REG", "baseline": baseline, "details": details}
    
    # LAT regression: if today's latency is significantly worse than baseline
    if base_lat > 0 and today_lat > base_lat:
        rel_delta = abs(today_lat - base_lat) / base_lat
        if rel_delta > threshold:
            return {"ok": False, "reason": "LAT_REG", "baseline": baseline, "details": details}
    
    # TAKER regression: if today's taker share is significantly worse than baseline
    if base_taker > 0 and today_taker > base_taker:
        rel_delta = abs(today_taker - base_taker) / base_taker
        if rel_delta > threshold:
            return {"ok": False, "reason": "TAKER_REG", "baseline": baseline, "details": details}
    
    return {"ok": True, "reason": "NONE", "baseline": baseline, "details": details}


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Regression Guard: Detect performance regression")
    parser.add_argument(
        "--today-json",
        type=str,
        required=True,
        help="Today's report JSON file"
    )
    parser.add_argument(
        "--history-dir",
        type=str,
        required=True,
        help="Directory with historical reports (REPORT_SOAK_*.json)"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.10,
        help="Regression threshold (e.g., 0.10 for 10%%)"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="artifacts/soak/latest/REGRESSION_GUARD_RESULT.json",
        help="Output JSON file"
    )
    
    args = parser.parse_args()
    
    # Load today's report
    with open(args.today_json, "r", encoding="utf-8") as f:
        today = json.load(f)
    
    # Load historical reports
    import glob
    history = []
    for path in sorted(glob.glob(str(Path(args.history_dir) / "REPORT_SOAK_*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            history.append(json.load(f))
    
    # Run check
    res = check(today, history, threshold=args.threshold)
    
    # Ensure output directory exists
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    
    # Write result
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    
    print(f"[OK] regression_guard result written: {args.out}")
    print(f"     Status: {'PASS' if res['ok'] else 'FAIL'} ({res['reason']})")
    
    return 0 if res['ok'] else 1


if __name__ == "__main__":
    sys.exit(main())

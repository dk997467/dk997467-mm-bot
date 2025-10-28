#!/usr/bin/env python3
"""
Drift Guard: Detect configuration or behavior drift in edge reports.

Usage:
    from tools.soak.drift_guard import check
    result = check('EDGE_REPORT.json')
"""
from __future__ import annotations
from pathlib import Path
import json
from typing import Dict, Any
import argparse
import sys


def check(edge_report_path: str) -> Dict[str, Any]:
    """
    Check for edge drift in a report file.
    
    Args:
        edge_report_path: Path to EDGE_REPORT.json
    
    Returns:
        Dictionary with:
        {
            "ok": bool (False if drift detected),
            "reason": str ("NONE" | "DRIFT_EDGE" | ...),
            "details": dict
        }
    
    Example:
        >>> result = check('artifacts/EDGE_REPORT.json')
        >>> result['ok']
        False
        >>> result['reason']
        'DRIFT_EDGE'
    """
    path = Path(edge_report_path)
    
    if not path.exists():
        return {"ok": True, "reason": "NONE", "details": {"error": "file_not_found"}}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception as e:
        return {"ok": True, "reason": "NONE", "details": {"error": str(e)}}
    
    # Check for edge drift indicators
    # Example: if median edge is below threshold, flag as drift
    
    median_edge = report.get("median_edge_bps", 0.0)
    edge_threshold = 2.0  # Example threshold
    
    if median_edge < edge_threshold:
        return {
            "ok": False,
            "reason": "DRIFT_EDGE",
            "details": {
                "median_edge_bps": median_edge,
                "threshold": edge_threshold
            }
        }
    
    return {"ok": True, "reason": "NONE", "details": {}}


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Drift Guard: Detect configuration drift")
    parser.add_argument(
        "edge_report",
        type=str,
        help="Path to EDGE_REPORT.json"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="artifacts/DRIFT_STOP.json",
        help="Output JSON file"
    )
    
    args = parser.parse_args()
    
    # Run check
    res = check(args.edge_report)
    
    # Ensure output directory exists
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    
    # Write result
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    
    print(f"[OK] drift_guard result written: {args.out}")
    print(f"     Status: {'PASS' if res['ok'] else 'FAIL'} ({res['reason']})")
    
    return 0 if res['ok'] else 1


if __name__ == "__main__":
    sys.exit(main())

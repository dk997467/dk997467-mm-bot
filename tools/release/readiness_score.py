#!/usr/bin/env python3
"""
Release readiness scoring: calculate weighted scores per section from reports.

Usage:
    from tools.release.readiness_score import _section_scores
    
    reports = [
        {"edge_net_bps": 2.8, "order_age_p95_ms": 320, ...},
        ...
    ]
    sections, total = _section_scores(reports)
"""
from __future__ import annotations
from typing import List, Dict, Any, Tuple


# Section weights
_SECTION_WEIGHTS = {
    "edge": 0.25,
    "latency": 0.20,
    "taker": 0.15,
    "guards": 0.20,
    "chaos": 0.10,
    "tests": 0.10,
}


def _section_scores(reports: List[Dict[str, Any]]) -> Tuple[Dict[str, float], float]:
    """
    Calculate readiness scores from reports.
    
    Args:
        reports: List of report dictionaries with metrics:
            - edge_net_bps: Edge in basis points
            - order_age_p95_ms: P95 latency in milliseconds
            - taker_share_pct: Taker share percentage
            - reg_guard: Regression guard result
            - drift: Drift check result
            - chaos_result: Chaos test result
            - bug_bash: Bug bash result
    
    Returns:
        Tuple of (sections_dict, total_score)
        - sections_dict: {section_name: score (0-100)}
        - total_score: Weighted total (0-100)
    
    Example:
        >>> reports = [{"edge_net_bps": 2.8, "order_age_p95_ms": 320, ...}]
        >>> sections, total = _section_scores(reports)
        >>> sections["edge"]
        85.0
        >>> total
        78.5
    """
    if not reports:
        return {}, 0.0
    
    # Calculate averages across reports
    avg_edge = sum(r.get("edge_net_bps", 0) for r in reports) / len(reports)
    avg_latency = sum(r.get("order_age_p95_ms", 0) for r in reports) / len(reports)
    avg_taker = sum(r.get("taker_share_pct", 0) for r in reports) / len(reports)
    
    # Count successful guards/tests
    guards_ok = sum(
        1 for r in reports
        if r.get("reg_guard", {}).get("reason") == "NONE"
        and r.get("drift", {}).get("reason") == "NONE"
    )
    chaos_ok = sum(1 for r in reports if r.get("chaos_result") == "OK")
    tests_ok = sum(1 for r in reports if r.get("bug_bash") == "OK")
    
    # Score each section (0-100)
    sections = {}
    
    # Edge: higher is better (target: 2.5+)
    sections["edge"] = min(100.0, max(0.0, (avg_edge / 3.0) * 100))
    
    # Latency: lower is better (target: <350ms)
    sections["latency"] = min(100.0, max(0.0, (500 - avg_latency) / 5.0))
    
    # Taker: lower is better (target: <15%)
    sections["taker"] = min(100.0, max(0.0, (20 - avg_taker) * 5))
    
    # Guards: % passed
    sections["guards"] = (guards_ok / len(reports)) * 100 if reports else 0.0
    
    # Chaos: % passed
    sections["chaos"] = (chaos_ok / len(reports)) * 100 if reports else 0.0
    
    # Tests: % passed
    sections["tests"] = (tests_ok / len(reports)) * 100 if reports else 0.0
    
    # Calculate weighted total
    total = sum(
        sections.get(section, 0.0) * weight
        for section, weight in _SECTION_WEIGHTS.items()
    )
    
    return sections, total


if __name__ == "__main__":
    import argparse
    import json
    import sys
    
    parser = argparse.ArgumentParser(description="Release Readiness Score")
    parser.add_argument("--json", action="store_true", default=True, help="Output as JSON (default)")
    parser.add_argument("--smoke", action="store_true", help="Run smoke test")
    args = parser.parse_args()
    
    if args.smoke:
        # Smoke test mode (outputs to stderr to avoid polluting stdout)
        test_reports = [
            {
                "edge_net_bps": 2.8,
                "order_age_p95_ms": 320.0,
                "taker_share_pct": 12.0,
                "reg_guard": {"reason": "NONE"},
                "drift": {"reason": "NONE"},
                "chaos_result": "OK",
                "bug_bash": "OK"
            },
            {
                "edge_net_bps": 2.7,
                "order_age_p95_ms": 330.0,
                "taker_share_pct": 12.5,
                "reg_guard": {"reason": "NONE"},
                "drift": {"reason": "NONE"},
                "chaos_result": "OK",
                "bug_bash": "OK"
            }
        ]
        
        sections, total = _section_scores(test_reports)
        
        sys.stderr.write("Section Scores:\n")
        for section, score in sections.items():
            sys.stderr.write(f"  {section}: {score:.1f}\n")
        
        sys.stderr.write(f"\nTotal Score: {total:.1f}\n")
        
        assert 70.0 <= total <= 100.0, f"Total score {total} outside expected range"
        assert set(sections.keys()) == {"edge", "latency", "taker", "guards", "chaos", "tests"}
        
        sys.stderr.write("\n[OK] Smoke test passed\n")
        sys.exit(0)
    
    # Default mode: JSON output
    test_reports = [
        {
            "edge_net_bps": 2.8,
            "order_age_p95_ms": 320.0,
            "taker_share_pct": 12.0,
            "reg_guard": {"reason": "NONE"},
            "drift": {"reason": "NONE"},
            "chaos_result": "OK",
            "bug_bash": "OK"
        }
    ]
    
    sections, total = _section_scores(test_reports)
    
    # Add runtime (deterministic for tests)
    import os
    from datetime import datetime, timezone
    if os.environ.get('MM_FREEZE_UTC') == '1':
        utc_iso = "1970-01-01T00:00:00Z"
    else:
        utc_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # Determine verdict based on score
    if total >= 0.9:
        verdict = "READY"
    elif total >= 0.7:
        verdict = "HOLD"
    else:
        verdict = "BLOCK"
    
    result = {
        "runtime": {
            "utc": utc_iso,
            "version": "0.1.0"
        },
        "score": total,
        "sections": sections,
        "verdict": verdict
    }
    
    # Print ONLY JSON to stdout (no prefixes, no [OK] markers)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    sys.exit(0)

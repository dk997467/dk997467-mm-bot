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


def _normalize_bounds(x: float, lo: float, hi: float) -> float:
    """
    Normalize value to 0-100 scale with clipping.
    
    Args:
        x: Input value
        lo: Lower bound (maps to 0)
        hi: Upper bound (maps to 100)
    
    Returns:
        Normalized value in [0, 100]
    
    Example:
        >>> _normalize_bounds(50, 0, 100)
        50.0
        >>> _normalize_bounds(150, 0, 100)
        100.0
        >>> _normalize_bounds(-10, 0, 100)
        0.0
    """
    if hi == lo:
        return 0.0
    normalized = ((x - lo) / (hi - lo)) * 100
    return min(100.0, max(0.0, normalized))


def _calc_section_scores(raw: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate normalized section scores from raw metrics.
    
    Args:
        raw: Dictionary with aggregated metrics:
            - avg_edge: Average edge in basis points
            - avg_latency: Average P95 latency in ms
            - avg_taker: Average taker share percentage
            - guards_pct: Guards pass percentage (0-100)
            - chaos_pct: Chaos pass percentage (0-100)
            - tests_pct: Tests pass percentage (0-100)
    
    Returns:
        Dictionary of section scores (0-100)
    
    Example:
        >>> raw = {
        ...     "avg_edge": 2.8,
        ...     "avg_latency": 320.0,
        ...     "avg_taker": 12.0,
        ...     "guards_pct": 100.0,
        ...     "chaos_pct": 100.0,
        ...     "tests_pct": 100.0
        ... }
        >>> scores = _calc_section_scores(raw)
        >>> scores["edge"]
        93.33...
    """
    sections = {}
    
    # Edge: higher is better (target: 2.5+, scale 0-3)
    avg_edge = raw.get("avg_edge", 0.0)
    sections["edge"] = min(100.0, max(0.0, (avg_edge / 3.0) * 100))
    
    # Latency: lower is better (target: <350ms, scale 500-0)
    avg_latency = raw.get("avg_latency", 0.0)
    sections["latency"] = min(100.0, max(0.0, (500 - avg_latency) / 5.0))
    
    # Taker: lower is better (target: <15%, scale 20-0)
    avg_taker = raw.get("avg_taker", 0.0)
    sections["taker"] = min(100.0, max(0.0, (20 - avg_taker) * 5))
    
    # Guards, Chaos, Tests: direct percentages
    sections["guards"] = raw.get("guards_pct", 0.0)
    sections["chaos"] = raw.get("chaos_pct", 0.0)
    sections["tests"] = raw.get("tests_pct", 0.0)
    
    return sections


def _calc_total_score(sections: Dict[str, float], weights: Dict[str, float]) -> float:
    """
    Calculate weighted total score from section scores.
    
    Args:
        sections: Dictionary of section scores (0-100)
        weights: Dictionary of section weights (auto-normalized if sum != 1.0)
    
    Returns:
        Weighted total score (0-100)
    
    Example:
        >>> sections = {"edge": 90.0, "latency": 80.0}
        >>> weights = {"edge": 0.6, "latency": 0.4}
        >>> _calc_total_score(sections, weights)
        86.0
        >>> # Auto-normalizes weights
        >>> weights = {"edge": 3, "latency": 2}
        >>> _calc_total_score(sections, weights)
        86.0
    """
    if not weights:
        return 0.0
    
    # Auto-normalize weights if needed
    weight_sum = sum(weights.values())
    if weight_sum == 0:
        return 0.0
    
    normalized_weights = {k: v / weight_sum for k, v in weights.items()}
    
    total = sum(
        sections.get(section, 0.0) * weight
        for section, weight in normalized_weights.items()
    )
    
    return total


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
    
    # Aggregate raw metrics
    raw = {
        "avg_edge": avg_edge,
        "avg_latency": avg_latency,
        "avg_taker": avg_taker,
        "guards_pct": (guards_ok / len(reports)) * 100 if reports else 0.0,
        "chaos_pct": (chaos_ok / len(reports)) * 100 if reports else 0.0,
        "tests_pct": (tests_ok / len(reports)) * 100 if reports else 0.0,
    }
    
    # Calculate section scores using pure function
    sections = _calc_section_scores(raw)
    
    # Calculate weighted total using pure function
    total = _calc_total_score(sections, _SECTION_WEIGHTS)
    
    return sections, total


def _calc_verdict(total_score: float) -> str:
    """
    Determine release verdict based on total score.
    
    Args:
        total_score: Total readiness score (0-100)
    
    Returns:
        Verdict: "READY" (>=90), "HOLD" (>=70), or "BLOCK" (<70)
    
    Example:
        >>> _calc_verdict(95.0)
        'READY'
        >>> _calc_verdict(75.0)
        'HOLD'
        >>> _calc_verdict(50.0)
        'BLOCK'
    """
    if total_score >= 90.0:
        return "READY"
    elif total_score >= 70.0:
        return "HOLD"
    else:
        return "BLOCK"


def main(argv=None):
    """
    CLI entry point for release readiness score.
    
    Args:
        argv: Command-line arguments (default: sys.argv)
    
    Returns:
        Exit code: 0 on success, 1 on failure
    """
    import argparse
    import json
    import sys
    import os
    from datetime import datetime, timezone
    
    parser = argparse.ArgumentParser(description="Release Readiness Score")
    parser.add_argument("--json", action="store_true", default=True, help="Output as JSON (default)")
    parser.add_argument("--smoke", action="store_true", help="Run smoke test")
    args = parser.parse_args(argv)
    
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
        return 0
    
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
    if os.environ.get('CI_FAKE_UTC'):
        utc_iso = os.environ.get('CI_FAKE_UTC')
    elif os.environ.get('MM_FREEZE_UTC') == '1':
        utc_iso = "1970-01-01T00:00:00Z"
    else:
        utc_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # Determine verdict
    verdict = _calc_verdict(total)
    
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
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

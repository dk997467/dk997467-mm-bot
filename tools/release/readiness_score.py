#!/usr/bin/env python3
"""
Release readiness scoring: calculate weighted scores per section.

Usage:
    from tools.release.readiness_score import _section_scores
    
    stats = {"docs": 0.8, "tests": 0.9, "ci": 1.0}
    scores = _section_scores(stats)
    print(scores["total"]["weighted"])  # Overall score
"""
from __future__ import annotations
from typing import Dict


# Section weights (must sum to 1.0)
_SECTION_WEIGHTS = {
    "docs": 0.20,
    "tests": 0.30,
    "ci": 0.20,
    "security": 0.15,
    "ops": 0.15,
}


def _section_scores(stats: Dict[str, float]) -> Dict[str, Dict[str, float]]:
    """
    Calculate weighted scores for each section.
    
    Args:
        stats: Dictionary of {section: raw_score (0.0-1.0)}
    
    Returns:
        Dictionary of {section: {"raw": float, "weighted": float}}
        Also includes "total" key with overall score.
    
    Example:
        >>> stats = {"docs": 0.8, "tests": 0.9, "ci": 1.0}
        >>> scores = _section_scores(stats)
        >>> scores["docs"]["raw"]
        0.8
        >>> scores["docs"]["weighted"]
        0.16  # 0.8 * 0.20
    """
    out = {}
    total_weighted = 0.0
    
    for section, weight in _SECTION_WEIGHTS.items():
        raw = float(stats.get(section, 0.0))
        
        # Clamp to [0.0, 1.0]
        raw = max(0.0, min(raw, 1.0))
        
        weighted = raw * weight
        
        out[section] = {
            "raw": raw,
            "weighted": weighted
        }
        
        total_weighted += weighted
    
    # Add total
    out["total"] = {
        "raw": total_weighted,
        "weighted": total_weighted
    }
    
    return out


if __name__ == "__main__":
    # Smoke test
    test_stats = {
        "docs": 0.8,
        "tests": 0.9,
        "ci": 1.0,
        "security": 0.7,
        "ops": 0.85
    }
    
    scores = _section_scores(test_stats)
    
    print("Section Scores:")
    for section, values in scores.items():
        print(f"  {section}: raw={values['raw']:.2f}, weighted={values['weighted']:.3f}")
    
    # Verify total
    expected_total = (0.8*0.20 + 0.9*0.30 + 1.0*0.20 + 0.7*0.15 + 0.85*0.15)
    assert abs(scores["total"]["weighted"] - expected_total) < 0.001
    
    print(f"\n[OK] Smoke test passed. Total score: {scores['total']['weighted']:.3f}")

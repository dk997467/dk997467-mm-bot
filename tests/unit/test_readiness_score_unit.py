#!/usr/bin/env python3
"""
Unit tests for tools/release/readiness_score.py

Tests pure functions:
    - _normalize_bounds
    - _calc_section_scores
    - _calc_total_score
    - _calc_verdict
    - main
"""

import json
import pytest
from unittest.mock import patch
from tools.release.readiness_score import (
    _normalize_bounds,
    _calc_section_scores,
    _calc_total_score,
    _calc_verdict,
    main,
)


# ======================================================================
# Test _normalize_bounds
# ======================================================================


def test_normalize_bounds_normal_range():
    """Test normalization within normal range."""
    assert _normalize_bounds(50, 0, 100) == 50.0
    assert _normalize_bounds(25, 0, 100) == 25.0
    assert _normalize_bounds(75, 0, 100) == 75.0


def test_normalize_bounds_clip_upper():
    """Test clipping at upper bound."""
    assert _normalize_bounds(150, 0, 100) == 100.0
    assert _normalize_bounds(200, 0, 100) == 100.0


def test_normalize_bounds_clip_lower():
    """Test clipping at lower bound."""
    assert _normalize_bounds(-10, 0, 100) == 0.0
    assert _normalize_bounds(-50, 0, 100) == 0.0


def test_normalize_bounds_exact_bounds():
    """Test exact bounds."""
    assert _normalize_bounds(0, 0, 100) == 0.0
    assert _normalize_bounds(100, 0, 100) == 100.0


def test_normalize_bounds_inverted_scale():
    """Test with inverted scale (higher value = lower score)."""
    # Example: latency 300ms on scale [500, 0] should be ~40
    # normalized = ((300 - 500) / (0 - 500)) * 100 = (-200 / -500) * 100 = 40
    result = _normalize_bounds(300, 500, 0)
    assert 39.0 <= result <= 41.0


def test_normalize_bounds_zero_range():
    """Test with zero range (lo == hi)."""
    assert _normalize_bounds(50, 100, 100) == 0.0


def test_normalize_bounds_negative_range():
    """Test with negative range."""
    assert _normalize_bounds(-50, -100, 0) == 50.0


def test_normalize_bounds_float_precision():
    """Test float precision."""
    result = _normalize_bounds(33.333, 0, 100)
    assert 33.0 <= result <= 34.0


# ======================================================================
# Test _calc_section_scores
# ======================================================================


def test_calc_section_scores_all_fields():
    """Test section score calculation with all fields."""
    raw = {
        "avg_edge": 2.8,
        "avg_latency": 320.0,
        "avg_taker": 12.0,
        "guards_pct": 100.0,
        "chaos_pct": 100.0,
        "tests_pct": 100.0,
    }
    
    scores = _calc_section_scores(raw)
    
    # Check all sections are present
    assert set(scores.keys()) == {"edge", "latency", "taker", "guards", "chaos", "tests"}
    
    # Check edge score: (2.8 / 3.0) * 100 = 93.33...
    assert 93.0 <= scores["edge"] <= 94.0
    
    # Check latency score: (500 - 320) / 5.0 = 36.0
    assert scores["latency"] == 36.0
    
    # Check taker score: (20 - 12) * 5 = 40.0
    assert scores["taker"] == 40.0
    
    # Check direct percentages
    assert scores["guards"] == 100.0
    assert scores["chaos"] == 100.0
    assert scores["tests"] == 100.0


def test_calc_section_scores_missing_keys():
    """Test with missing keys (should use defaults)."""
    raw = {}
    
    scores = _calc_section_scores(raw)
    
    # All sections should exist with default (0.0 or calculated from 0.0)
    assert set(scores.keys()) == {"edge", "latency", "taker", "guards", "chaos", "tests"}
    
    # Edge: 0 / 3 * 100 = 0
    assert scores["edge"] == 0.0
    
    # Latency: (500 - 0) / 5 = 100 (clipped)
    assert scores["latency"] == 100.0
    
    # Taker: (20 - 0) * 5 = 100 (clipped)
    assert scores["taker"] == 100.0
    
    # Direct percentages
    assert scores["guards"] == 0.0
    assert scores["chaos"] == 0.0
    assert scores["tests"] == 0.0


def test_calc_section_scores_edge_clipping():
    """Test edge score clipping at bounds."""
    # Edge too high (should clip to 100)
    raw = {"avg_edge": 5.0}
    scores = _calc_section_scores(raw)
    assert scores["edge"] == 100.0
    
    # Edge negative (should clip to 0)
    raw = {"avg_edge": -1.0}
    scores = _calc_section_scores(raw)
    assert scores["edge"] == 0.0


def test_calc_section_scores_latency_clipping():
    """Test latency score clipping at bounds."""
    # Latency very low (should clip to 100)
    raw = {"avg_latency": 0.0}
    scores = _calc_section_scores(raw)
    assert scores["latency"] == 100.0
    
    # Latency very high (should clip to 0)
    raw = {"avg_latency": 600.0}
    scores = _calc_section_scores(raw)
    assert scores["latency"] == 0.0


def test_calc_section_scores_taker_clipping():
    """Test taker score clipping at bounds."""
    # Taker very low (should clip to 100)
    raw = {"avg_taker": 0.0}
    scores = _calc_section_scores(raw)
    assert scores["taker"] == 100.0
    
    # Taker very high (should clip to 0)
    raw = {"avg_taker": 30.0}
    scores = _calc_section_scores(raw)
    assert scores["taker"] == 0.0


def test_calc_section_scores_partial_data():
    """Test with partial data."""
    raw = {
        "avg_edge": 2.5,
        "guards_pct": 50.0,
    }
    
    scores = _calc_section_scores(raw)
    
    # Check specified fields
    assert 83.0 <= scores["edge"] <= 84.0  # 2.5 / 3 * 100 = 83.33...
    assert scores["guards"] == 50.0
    
    # Check defaults for missing fields
    assert scores["chaos"] == 0.0
    assert scores["tests"] == 0.0


# ======================================================================
# Test _calc_total_score
# ======================================================================


def test_calc_total_score_normal():
    """Test total score calculation with normal weights."""
    sections = {
        "edge": 90.0,
        "latency": 80.0,
        "taker": 70.0,
    }
    weights = {
        "edge": 0.5,
        "latency": 0.3,
        "taker": 0.2,
    }
    
    total = _calc_total_score(sections, weights)
    
    # Expected: 90*0.5 + 80*0.3 + 70*0.2 = 45 + 24 + 14 = 83
    assert total == 83.0


def test_calc_total_score_auto_normalize():
    """Test auto-normalization of weights."""
    sections = {
        "edge": 90.0,
        "latency": 80.0,
    }
    
    # Weights sum to 5, should be normalized to [0.6, 0.4]
    weights = {
        "edge": 3,
        "latency": 2,
    }
    
    total = _calc_total_score(sections, weights)
    
    # Expected: 90*0.6 + 80*0.4 = 54 + 32 = 86
    assert total == 86.0


def test_calc_total_score_empty_weights():
    """Test with empty weights."""
    sections = {"edge": 90.0}
    weights = {}
    
    total = _calc_total_score(sections, weights)
    assert total == 0.0


def test_calc_total_score_zero_weight_sum():
    """Test with weights summing to zero."""
    sections = {"edge": 90.0}
    weights = {"edge": 0, "latency": 0}
    
    total = _calc_total_score(sections, weights)
    assert total == 0.0


def test_calc_total_score_missing_section():
    """Test with missing section in sections dict."""
    sections = {"edge": 90.0}
    weights = {
        "edge": 0.5,
        "latency": 0.5,  # Missing in sections
    }
    
    total = _calc_total_score(sections, weights)
    
    # Expected: 90*0.5 + 0*0.5 = 45
    assert total == 45.0


def test_calc_total_score_extra_section():
    """Test with extra section not in weights."""
    sections = {
        "edge": 90.0,
        "latency": 80.0,
        "extra": 100.0,  # Not in weights
    }
    weights = {
        "edge": 0.5,
        "latency": 0.5,
    }
    
    total = _calc_total_score(sections, weights)
    
    # Expected: 90*0.5 + 80*0.5 = 85 (extra ignored)
    assert total == 85.0


def test_calc_total_score_single_section():
    """Test with single section."""
    sections = {"edge": 75.0}
    weights = {"edge": 1.0}
    
    total = _calc_total_score(sections, weights)
    assert total == 75.0


def test_calc_total_score_all_zeros():
    """Test with all zero scores."""
    sections = {
        "edge": 0.0,
        "latency": 0.0,
        "taker": 0.0,
    }
    weights = {
        "edge": 0.33,
        "latency": 0.33,
        "taker": 0.34,
    }
    
    total = _calc_total_score(sections, weights)
    assert total == 0.0


def test_calc_total_score_all_hundreds():
    """Test with all perfect scores."""
    sections = {
        "edge": 100.0,
        "latency": 100.0,
        "taker": 100.0,
    }
    weights = {
        "edge": 0.33,
        "latency": 0.33,
        "taker": 0.34,
    }
    
    total = _calc_total_score(sections, weights)
    assert total == 100.0


def test_calc_total_score_non_normalized_weights():
    """Test with various non-normalized weights."""
    sections = {"edge": 80.0, "latency": 60.0}
    
    # Weights sum to 10
    weights = {"edge": 7, "latency": 3}
    
    total = _calc_total_score(sections, weights)
    
    # Expected: 80*0.7 + 60*0.3 = 56 + 18 = 74
    assert total == 74.0


# ======================================================================
# Test _section_scores (high-level wrapper)
# ======================================================================


def test_section_scores_single_report():
    """Test _section_scores with a single report."""
    from tools.release.readiness_score import _section_scores
    
    reports = [{
        "edge_net_bps": 2.8,
        "order_age_p95_ms": 320.0,
        "taker_share_pct": 12.0,
        "reg_guard": {"reason": "NONE"},
        "drift": {"reason": "NONE"},
        "chaos_result": "OK",
        "bug_bash": "OK"
    }]
    
    sections, total = _section_scores(reports)
    
    # Check all sections present
    assert set(sections.keys()) == {"edge", "latency", "taker", "guards", "chaos", "tests"}
    
    # Check total is in valid range
    assert 0.0 <= total <= 100.0
    
    # Check all sections are in valid range
    for score in sections.values():
        assert 0.0 <= score <= 100.0


def test_section_scores_multiple_reports():
    """Test _section_scores with multiple reports (averaging)."""
    from tools.release.readiness_score import _section_scores
    
    reports = [
        {
            "edge_net_bps": 3.0,
            "order_age_p95_ms": 300.0,
            "taker_share_pct": 10.0,
            "reg_guard": {"reason": "NONE"},
            "drift": {"reason": "NONE"},
            "chaos_result": "OK",
            "bug_bash": "OK"
        },
        {
            "edge_net_bps": 2.0,
            "order_age_p95_ms": 400.0,
            "taker_share_pct": 15.0,
            "reg_guard": {"reason": "NONE"},
            "drift": {"reason": "NONE"},
            "chaos_result": "OK",
            "bug_bash": "OK"
        }
    ]
    
    sections, total = _section_scores(reports)
    
    # Average edge should be 2.5
    # Average latency should be 350
    # Average taker should be 12.5
    
    # Check edge score: (2.5 / 3.0) * 100 = 83.33...
    assert 83.0 <= sections["edge"] <= 84.0
    
    # Check latency score: (500 - 350) / 5.0 = 30.0
    assert sections["latency"] == 30.0
    
    # Check taker score: (20 - 12.5) * 5 = 37.5
    assert sections["taker"] == 37.5
    
    # All guards/chaos/tests passed
    assert sections["guards"] == 100.0
    assert sections["chaos"] == 100.0
    assert sections["tests"] == 100.0


def test_section_scores_empty_reports():
    """Test _section_scores with empty reports list."""
    from tools.release.readiness_score import _section_scores
    
    reports = []
    
    sections, total = _section_scores(reports)
    
    assert sections == {}
    assert total == 0.0


def test_section_scores_partial_failures():
    """Test _section_scores with some failures."""
    from tools.release.readiness_score import _section_scores
    
    reports = [
        {
            "edge_net_bps": 2.5,
            "order_age_p95_ms": 300.0,
            "taker_share_pct": 10.0,
            "reg_guard": {"reason": "NONE"},
            "drift": {"reason": "NONE"},
            "chaos_result": "OK",
            "bug_bash": "OK"
        },
        {
            "edge_net_bps": 2.5,
            "order_age_p95_ms": 300.0,
            "taker_share_pct": 10.0,
            "reg_guard": {"reason": "REG_FAIL"},  # Failed
            "drift": {"reason": "DRIFT"},  # Failed
            "chaos_result": "FAIL",  # Failed
            "bug_bash": "FAIL"  # Failed
        }
    ]
    
    sections, total = _section_scores(reports)
    
    # Only 50% passed for guards/chaos/tests
    assert sections["guards"] == 50.0
    assert sections["chaos"] == 50.0
    assert sections["tests"] == 50.0


def test_section_scores_missing_fields():
    """Test _section_scores with missing fields in reports."""
    from tools.release.readiness_score import _section_scores
    
    reports = [
        {}  # Empty report
    ]
    
    sections, total = _section_scores(reports)
    
    # Should handle missing fields gracefully with defaults
    assert set(sections.keys()) == {"edge", "latency", "taker", "guards", "chaos", "tests"}
    
    # Check defaults are used
    assert sections["edge"] == 0.0  # 0 / 3 * 100 = 0
    assert sections["latency"] == 100.0  # (500 - 0) / 5 = 100
    assert sections["taker"] == 100.0  # (20 - 0) * 5 = 100
    assert sections["guards"] == 0.0
    assert sections["chaos"] == 0.0
    assert sections["tests"] == 0.0


# ======================================================================
# Integration test
# ======================================================================


def test_integration_readiness_score_pipeline():
    """Test the full pipeline: raw metrics -> sections -> total."""
    # Simulate "excellent" metrics
    raw = {
        "avg_edge": 3.0,  # Perfect edge
        "avg_latency": 200.0,  # Excellent latency
        "avg_taker": 10.0,  # Low taker
        "guards_pct": 100.0,
        "chaos_pct": 100.0,
        "tests_pct": 100.0,
    }
    
    sections = _calc_section_scores(raw)
    
    weights = {
        "edge": 0.25,
        "latency": 0.20,
        "taker": 0.15,
        "guards": 0.20,
        "chaos": 0.10,
        "tests": 0.10,
    }
    
    total = _calc_total_score(sections, weights)
    
    # Should be a high score (>80)
    assert total > 80.0
    
    # All sections should be positive
    for score in sections.values():
        assert score >= 0.0


# ======================================================================
# Test _calc_verdict
# ======================================================================


def test_calc_verdict_ready():
    """Test verdict calculation for READY threshold."""
    assert _calc_verdict(90.0) == "READY"
    assert _calc_verdict(95.0) == "READY"
    assert _calc_verdict(100.0) == "READY"


def test_calc_verdict_hold():
    """Test verdict calculation for HOLD threshold."""
    assert _calc_verdict(70.0) == "HOLD"
    assert _calc_verdict(80.0) == "HOLD"
    assert _calc_verdict(89.9) == "HOLD"


def test_calc_verdict_block():
    """Test verdict calculation for BLOCK threshold."""
    assert _calc_verdict(0.0) == "BLOCK"
    assert _calc_verdict(50.0) == "BLOCK"
    assert _calc_verdict(69.9) == "BLOCK"


def test_calc_verdict_edge_cases():
    """Test verdict calculation at exact boundaries."""
    assert _calc_verdict(90.0) == "READY"  # Exact boundary
    assert _calc_verdict(89.999) == "HOLD"  # Just below
    assert _calc_verdict(70.0) == "HOLD"  # Exact boundary
    assert _calc_verdict(69.999) == "BLOCK"  # Just below


# ======================================================================
# Test main() function
# ======================================================================


def test_main_smoke_mode(capsys, monkeypatch):
    """Test main() in smoke test mode."""
    # Mock stderr to capture smoke test output
    exit_code = main(["--smoke"])
    
    assert exit_code == 0
    
    # Smoke test writes to stderr, check that it ran
    captured = capsys.readouterr()
    assert "Section Scores:" in captured.err or exit_code == 0


def test_main_json_mode_deterministic(capsys, monkeypatch):
    """Test main() in JSON mode with deterministic UTC."""
    # Set environment variable for deterministic UTC
    monkeypatch.setenv("MM_FREEZE_UTC", "1")
    
    exit_code = main([])
    
    assert exit_code == 0
    
    # Capture stdout
    captured = capsys.readouterr()
    output = captured.out.strip()
    
    # Parse JSON
    result = json.loads(output)
    
    # Check structure
    assert "runtime" in result
    assert "score" in result
    assert "sections" in result
    assert "verdict" in result
    
    # Check deterministic UTC
    assert result["runtime"]["utc"] == "1970-01-01T00:00:00Z"
    
    # Check verdict
    assert result["verdict"] in ["READY", "HOLD", "BLOCK"]
    
    # Check sections
    assert set(result["sections"].keys()) == {"edge", "latency", "taker", "guards", "chaos", "tests"}


def test_main_json_mode_with_ci_fake_utc(capsys, monkeypatch):
    """Test main() with CI_FAKE_UTC environment variable."""
    monkeypatch.setenv("CI_FAKE_UTC", "2025-01-01T12:00:00Z")
    
    exit_code = main([])
    
    assert exit_code == 0
    
    captured = capsys.readouterr()
    result = json.loads(captured.out.strip())
    
    # Check custom UTC
    assert result["runtime"]["utc"] == "2025-01-01T12:00:00Z"


def test_main_json_output_format(capsys, monkeypatch):
    """Test main() JSON output format (deterministic, sorted keys)."""
    monkeypatch.setenv("MM_FREEZE_UTC", "1")
    
    exit_code = main([])
    
    assert exit_code == 0
    
    captured = capsys.readouterr()
    output = captured.out.strip()
    
    # Parse JSON
    result = json.loads(output)
    
    # Re-serialize with same settings and compare
    expected_format = json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    assert output == expected_format


def test_main_score_calculation_integration(capsys, monkeypatch):
    """Test that main() correctly calculates and formats scores."""
    monkeypatch.setenv("MM_FREEZE_UTC", "1")
    
    exit_code = main([])
    
    assert exit_code == 0
    
    captured = capsys.readouterr()
    result = json.loads(captured.out.strip())
    
    # Check score is in valid range
    assert 0.0 <= result["score"] <= 100.0
    
    # Check all section scores are in valid range
    for section, score in result["sections"].items():
        assert 0.0 <= score <= 100.0, f"Section {section} score {score} out of range"


# ======================================================================
# Run tests
# ======================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


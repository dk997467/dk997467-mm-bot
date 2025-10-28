#!/usr/bin/env python3
"""
Unit tests for tools/region/run_canary_compare.py

Tests pure functions:
    - _aggregate_metrics
    - _find_best_window
    - _find_best_region
"""

import pytest
from tools.region.run_canary_compare import (
    _aggregate_metrics,
    _find_best_window,
    _find_best_region,
)


# ======================================================================
# Test _aggregate_metrics
# ======================================================================


def test_aggregate_metrics_single_metric():
    """Test aggregation with single metric."""
    metrics = [
        {"fill_rate": 0.8, "net_bps": 2.5, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0}
    ]
    
    result = _aggregate_metrics(metrics)
    
    assert result["fill_rate"] == 0.8
    assert result["net_bps"] == 2.5
    assert result["order_age_p95_ms"] == 300.0
    assert result["taker_share_pct"] == 10.0


def test_aggregate_metrics_multiple_metrics():
    """Test aggregation with multiple metrics (averaging)."""
    metrics = [
        {"fill_rate": 0.8, "net_bps": 2.0, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0},
        {"fill_rate": 0.9, "net_bps": 3.0, "order_age_p95_ms": 400.0, "taker_share_pct": 15.0},
    ]
    
    result = _aggregate_metrics(metrics)
    
    # Averages: (0.8+0.9)/2=0.85, (2.0+3.0)/2=2.5, etc.
    assert abs(result["fill_rate"] - 0.85) < 1e-10  # Floating-point tolerance
    assert result["net_bps"] == 2.5
    assert result["order_age_p95_ms"] == 350.0
    assert result["taker_share_pct"] == 12.5


def test_aggregate_metrics_empty_list():
    """Test aggregation with empty metrics list."""
    result = _aggregate_metrics([])
    
    # Should return all zeros
    assert result["fill_rate"] == 0.0
    assert result["net_bps"] == 0.0
    assert result["order_age_p95_ms"] == 0.0
    assert result["taker_share_pct"] == 0.0


def test_aggregate_metrics_missing_keys():
    """Test aggregation with missing keys (defaults to 0)."""
    metrics = [
        {"fill_rate": 0.8},  # Missing other keys
        {"net_bps": 2.5},  # Missing other keys
    ]
    
    result = _aggregate_metrics(metrics)
    
    # Average fill_rate: (0.8 + 0) / 2 = 0.4
    # Average net_bps: (0 + 2.5) / 2 = 1.25
    assert result["fill_rate"] == 0.4
    assert result["net_bps"] == 1.25
    assert result["order_age_p95_ms"] == 0.0
    assert result["taker_share_pct"] == 0.0


# ======================================================================
# Test _find_best_window
# ======================================================================


def test_find_best_window_single_window():
    """Test with single window."""
    windows = {
        "window1": {"net_bps": 2.5, "order_age_p95_ms": 300.0}
    }
    
    best = _find_best_window(windows)
    assert best == "window1"


def test_find_best_window_different_net_bps():
    """Test with different net_bps (highest wins)."""
    windows = {
        "window1": {"net_bps": 2.0, "order_age_p95_ms": 300.0},
        "window2": {"net_bps": 3.0, "order_age_p95_ms": 400.0},
        "window3": {"net_bps": 2.5, "order_age_p95_ms": 350.0},
    }
    
    best = _find_best_window(windows)
    assert best == "window2"  # Highest net_bps


def test_find_best_window_equal_net_bps_tiebreak_by_latency():
    """Test tie-break: equal net_bps, lowest latency wins."""
    windows = {
        "window1": {"net_bps": 2.5, "order_age_p95_ms": 400.0},
        "window2": {"net_bps": 2.5, "order_age_p95_ms": 300.0},  # Same net_bps, lower latency
        "window3": {"net_bps": 2.5, "order_age_p95_ms": 350.0},
    }
    
    best = _find_best_window(windows)
    assert best == "window2"  # Lowest latency for equal net_bps


def test_find_best_window_empty_dict():
    """Test with empty windows dict."""
    with pytest.raises(ValueError, match="No windows provided"):
        _find_best_window({})


def test_find_best_window_stability():
    """Test that ranking is stable with identical parameters."""
    windows = {
        "window_a": {"net_bps": 2.5, "order_age_p95_ms": 300.0},
        "window_b": {"net_bps": 2.5, "order_age_p95_ms": 300.0},
    }
    
    # Should return the same result consistently
    best1 = _find_best_window(windows)
    best2 = _find_best_window(windows)
    
    assert best1 == best2
    assert best1 in ["window_a", "window_b"]


# ======================================================================
# Test _find_best_region
# ======================================================================


def test_find_best_region_single_region_safe():
    """Test with single safe region."""
    regions = {
        "us-east-1": {"net_bps": 2.6, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0}
    }
    
    best = _find_best_region(regions)
    assert best == "us-east-1"


def test_find_best_region_multiple_safe_regions():
    """Test with multiple safe regions (highest net_bps wins)."""
    regions = {
        "us-east-1": {"net_bps": 2.6, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0},
        "eu-west-1": {"net_bps": 2.8, "order_age_p95_ms": 320.0, "taker_share_pct": 12.0},
        "ap-southeast-1": {"net_bps": 2.5, "order_age_p95_ms": 310.0, "taker_share_pct": 11.0},
    }
    
    best = _find_best_region(regions)
    assert best == "eu-west-1"  # Highest net_bps among safe regions


def test_find_best_region_equal_net_bps_tiebreak_by_latency():
    """Test tie-break: equal net_bps, lowest latency wins."""
    regions = {
        "us-east-1": {"net_bps": 2.6, "order_age_p95_ms": 320.0, "taker_share_pct": 10.0},
        "eu-west-1": {"net_bps": 2.6, "order_age_p95_ms": 300.0, "taker_share_pct": 12.0},  # Same net_bps, lower latency
        "ap-southeast-1": {"net_bps": 2.6, "order_age_p95_ms": 310.0, "taker_share_pct": 11.0},
    }
    
    best = _find_best_region(regions)
    assert best == "eu-west-1"  # Lowest latency for equal net_bps


def test_find_best_region_no_safe_regions():
    """Test fallback when no regions meet safe criteria."""
    regions = {
        "us-east-1": {"net_bps": 2.0, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0},  # net_bps too low
        "eu-west-1": {"net_bps": 2.6, "order_age_p95_ms": 400.0, "taker_share_pct": 12.0},  # latency too high
        "ap-southeast-1": {"net_bps": 2.5, "order_age_p95_ms": 310.0, "taker_share_pct": 20.0},  # taker too high
    }
    
    best = _find_best_region(regions)
    # Should pick highest net_bps as fallback
    assert best == "eu-west-1"


def test_find_best_region_safe_criteria_boundary():
    """Test safe criteria boundaries."""
    # Exactly at boundaries (should be safe)
    regions = {
        "us-east-1": {"net_bps": 2.50, "order_age_p95_ms": 350.0, "taker_share_pct": 15.0}
    }
    
    best = _find_best_region(regions)
    assert best == "us-east-1"


def test_find_best_region_safe_criteria_just_below_boundary():
    """Test just below safe criteria boundaries."""
    regions = {
        "us-east-1": {"net_bps": 2.49, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0},  # Just below net_bps
        "eu-west-1": {"net_bps": 3.0, "order_age_p95_ms": 351.0, "taker_share_pct": 10.0},  # Just above latency
        "ap-southeast-1": {"net_bps": 2.6, "order_age_p95_ms": 300.0, "taker_share_pct": 15.1},  # Just above taker
    }
    
    best = _find_best_region(regions)
    # No safe regions, should pick highest net_bps
    assert best == "eu-west-1"


def test_find_best_region_missing_keys():
    """Test with missing keys (should use defaults that fail safe criteria)."""
    regions = {
        "us-east-1": {"net_bps": 3.0},  # Missing latency and taker (defaults to inf, fails safe)
        "eu-west-1": {"net_bps": 2.6, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0},  # Complete
    }
    
    best = _find_best_region(regions)
    # us-east-1 fails safe criteria due to missing keys, eu-west-1 should win
    assert best == "eu-west-1"


def test_find_best_region_empty_dict():
    """Test with empty regions dict."""
    with pytest.raises(ValueError, match="No regions provided"):
        _find_best_region({})


def test_find_best_region_stability():
    """Test that ranking is stable with identical parameters."""
    regions = {
        "region_a": {"net_bps": 2.6, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0},
        "region_b": {"net_bps": 2.6, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0},
    }
    
    # Should return the same result consistently
    best1 = _find_best_region(regions)
    best2 = _find_best_region(regions)
    
    assert best1 == best2
    assert best1 in ["region_a", "region_b"]


def test_find_best_region_all_criteria():
    """Test that all safe criteria are checked (net_bps, latency, taker)."""
    regions = {
        "fail_net_bps": {"net_bps": 2.0, "order_age_p95_ms": 300.0, "taker_share_pct": 10.0},
        "fail_latency": {"net_bps": 2.6, "order_age_p95_ms": 400.0, "taker_share_pct": 10.0},
        "fail_taker": {"net_bps": 2.6, "order_age_p95_ms": 300.0, "taker_share_pct": 20.0},
        "all_safe": {"net_bps": 2.5, "order_age_p95_ms": 310.0, "taker_share_pct": 12.0},
    }
    
    best = _find_best_region(regions)
    # Only "all_safe" meets all criteria
    assert best == "all_safe"


# ======================================================================
# Run tests
# ======================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

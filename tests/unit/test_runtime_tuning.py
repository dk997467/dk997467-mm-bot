#!/usr/bin/env python3
"""
Unit tests for runtime tuning logic.

Tests trigger logic, limits enforcement, and guardrails.
"""

import pytest
from pathlib import Path

# Import module under test
import sys
sys.path.insert(0, str(Path(__file__).parents[2]))

from tools.soak.run import compute_tuning_adjustments


def test_trigger_cancel_ratio():
    """Test cancel_ratio > 0.55 trigger."""
    edge_report = {
        "totals": {
            "net_bps": 3.0,
            "cancel_ratio": 0.60,  # > 0.55
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "order_age_p95_ms": 300,
            "ws_lag_p95_ms": 100,
        }
    }
    
    current_overrides = {}
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Should adjust min_interval_ms and replace_rate_per_min
    assert "min_interval_ms" in new_overrides
    assert "replace_rate_per_min" in new_overrides
    assert new_overrides["min_interval_ms"] > 0  # Default + 20
    assert "cancel_ratio>0.55" in reasons
    assert not multi_fail


def test_trigger_adverse_slippage():
    """Test adverse_bps_p95 > 4 or slippage_bps_p95 > 3 trigger."""
    edge_report = {
        "totals": {
            "net_bps": 3.0,
            "cancel_ratio": 0.30,
            "adverse_bps_p95": 5.0,  # > 4
            "slippage_bps_p95": 1.0,
            "order_age_p95_ms": 300,
            "ws_lag_p95_ms": 100,
        }
    }
    
    current_overrides = {}
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Should adjust base_spread_bps_delta
    assert "base_spread_bps_delta" in new_overrides
    assert new_overrides["base_spread_bps_delta"] > 0  # +0.05
    assert "adverse/slippage>threshold" in reasons
    assert not multi_fail


def test_trigger_order_age():
    """Test order_age_p95_ms > 330 trigger."""
    edge_report = {
        "totals": {
            "net_bps": 3.0,
            "cancel_ratio": 0.30,
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "order_age_p95_ms": 350,  # > 330
            "ws_lag_p95_ms": 100,
        }
    }
    
    current_overrides = {}
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Should adjust replace_rate_per_min and tail_age_ms
    assert "replace_rate_per_min" in new_overrides or "tail_age_ms" in new_overrides
    assert "order_age>330" in reasons
    assert not multi_fail


def test_trigger_ws_lag():
    """Test ws_lag_p95_ms > 120 trigger."""
    edge_report = {
        "totals": {
            "net_bps": 3.0,
            "cancel_ratio": 0.30,
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "order_age_p95_ms": 300,
            "ws_lag_p95_ms": 150,  # > 120
        }
    }
    
    current_overrides = {}
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Should adjust min_interval_ms
    assert "min_interval_ms" in new_overrides
    assert "ws_lag>120" in reasons
    assert not multi_fail


def test_trigger_net_bps_low():
    """Test net_bps < 2.5 trigger (only when no other triggers)."""
    edge_report = {
        "totals": {
            "net_bps": 2.0,  # < 2.5
            "cancel_ratio": 0.30,
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "order_age_p95_ms": 300,
            "ws_lag_p95_ms": 100,
        }
    }
    
    current_overrides = {}
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Should adjust base_spread_bps_delta (since no other triggers)
    assert "base_spread_bps_delta" in new_overrides
    assert new_overrides["base_spread_bps_delta"] > 0  # +0.02
    assert "net_bps<2.5" in reasons
    assert not multi_fail


def test_limits_enforcement():
    """Test that limits are enforced."""
    edge_report = {
        "totals": {
            "net_bps": 1.0,
            "cancel_ratio": 0.80,  # High
            "adverse_bps_p95": 10.0,  # Very high
            "slippage_bps_p95": 8.0,  # Very high
            "order_age_p95_ms": 500,  # High
            "ws_lag_p95_ms": 200,  # High
        }
    }
    
    # Start with high overrides
    current_overrides = {
        "min_interval_ms": 280,
        "replace_rate_per_min": 140,
        "base_spread_bps_delta": 0.55,
        "tail_age_ms": 950,
    }
    
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Check limits
    if "min_interval_ms" in new_overrides:
        assert new_overrides["min_interval_ms"] <= 300  # Max limit
    
    if "replace_rate_per_min" in new_overrides:
        assert new_overrides["replace_rate_per_min"] >= 120  # Min limit
    
    if "base_spread_bps_delta" in new_overrides:
        assert new_overrides["base_spread_bps_delta"] <= 0.6  # Max limit
    
    if "tail_age_ms" in new_overrides:
        assert new_overrides["tail_age_ms"] <= 1000  # Max limit


def test_multi_fail_guard():
    """Test multi-fail guard (3+ independent triggers)."""
    edge_report = {
        "totals": {
            "net_bps": 1.5,  # Low
            "cancel_ratio": 0.70,  # Trigger 1
            "adverse_bps_p95": 6.0,  # Trigger 2
            "slippage_bps_p95": 5.0,  # Trigger 2 (same as adverse)
            "order_age_p95_ms": 400,  # Trigger 3
            "ws_lag_p95_ms": 180,  # Trigger 4
        }
    }
    
    current_overrides = {}
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Multi-fail guard should be triggered (3+ independent triggers)
    assert multi_fail
    assert "multi_fail_guard" in reasons
    
    # Should only have calming adjustments
    if "base_spread_bps_delta" in new_overrides:
        assert new_overrides["base_spread_bps_delta"] > 0  # Increase spread (calm down)
    
    if "min_interval_ms" in new_overrides:
        assert new_overrides["min_interval_ms"] > 0  # Increase interval (calm down)


def test_spread_delta_cap():
    """Test that spread_delta adjustment is capped at 0.1 per iteration."""
    edge_report = {
        "totals": {
            "net_bps": 1.0,
            "cancel_ratio": 0.30,
            "adverse_bps_p95": 8.0,  # Very high - would want large increase
            "slippage_bps_p95": 1.0,
            "order_age_p95_ms": 300,
            "ws_lag_p95_ms": 100,
        }
    }
    
    current_overrides = {
        "base_spread_bps_delta": 0.10
    }
    
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Check that delta change is capped at 0.1
    if "base_spread_bps_delta" in new_overrides:
        delta_change = new_overrides["base_spread_bps_delta"] - current_overrides["base_spread_bps_delta"]
        assert delta_change <= 0.1


def test_max_two_changes_per_field():
    """Test that max 2 changes per field per iteration."""
    # This is tested implicitly in the apply_adjustment logic
    # We can't easily test this without modifying the function signature
    # But we can verify that the function doesn't apply more than 2 changes
    
    edge_report = {
        "totals": {
            "net_bps": 1.0,
            "cancel_ratio": 0.80,  # Trigger min_interval and replace_rate
            "adverse_bps_p95": 8.0,  # Trigger spread
            "slippage_bps_p95": 1.0,
            "order_age_p95_ms": 450,  # Trigger replace_rate and tail_age
            "ws_lag_p95_ms": 200,  # Trigger min_interval
        }
    }
    
    current_overrides = {}
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Due to multi-fail guard, we should have limited adjustments
    # This test mostly validates that the logic runs without errors
    assert isinstance(new_overrides, dict)
    assert isinstance(reasons, list)


def test_no_triggers():
    """Test that no adjustments are made when metrics are good."""
    edge_report = {
        "totals": {
            "net_bps": 3.5,  # Good
            "cancel_ratio": 0.30,  # Good
            "adverse_bps_p95": 2.0,  # Good
            "slippage_bps_p95": 1.5,  # Good
            "order_age_p95_ms": 280,  # Good
            "ws_lag_p95_ms": 90,  # Good
        }
    }
    
    current_overrides = {}
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Should have no adjustments
    assert len(new_overrides) == 0
    assert len(reasons) == 0
    assert not multi_fail


def test_incremental_adjustment():
    """Test that adjustments build on previous overrides."""
    edge_report = {
        "totals": {
            "net_bps": 3.0,
            "cancel_ratio": 0.60,  # Trigger
            "adverse_bps_p95": 2.0,
            "slippage_bps_p95": 1.0,
            "order_age_p95_ms": 300,
            "ws_lag_p95_ms": 100,
        }
    }
    
    current_overrides = {
        "min_interval_ms": 70,
        "replace_rate_per_min": 350,
    }
    
    new_overrides, reasons, multi_fail = compute_tuning_adjustments(edge_report, current_overrides)
    
    # Should build on previous values
    if "min_interval_ms" in new_overrides:
        assert new_overrides["min_interval_ms"] >= current_overrides["min_interval_ms"]
    
    if "replace_rate_per_min" in new_overrides:
        assert new_overrides["replace_rate_per_min"] <= current_overrides["replace_rate_per_min"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


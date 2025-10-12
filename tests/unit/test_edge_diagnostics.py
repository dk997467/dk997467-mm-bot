"""
Unit Tests: Edge Diagnostics (Component Breakdown + Block Reasons)

Tests for PROMPT H functionality:
- component_breakdown calculation
- neg_edge_drivers identification
- block_reasons statistics from audit.jsonl
"""

import pytest

from tools.reports.edge_metrics import (
    compute_component_breakdown,
    compute_neg_edge_drivers,
    compute_block_reasons,
)


def test_component_breakdown():
    """Test component breakdown calculation."""
    totals = {
        "gross_bps": 10.0,
        "fees_bps": 2.0,
        "slippage_bps": 1.5,
        "adverse_bps": 2.5,
        "inventory_bps": 0.5,
        "net_bps": 3.5,
    }
    
    breakdown = compute_component_breakdown(totals)
    
    assert breakdown["gross_bps"] == 10.0
    assert breakdown["fees_eff_bps"] == 2.0
    assert breakdown["slippage_bps"] == 1.5
    assert breakdown["adverse_bps"] == 2.5
    assert breakdown["inventory_bps"] == 0.5
    assert breakdown["net_bps"] == 3.5


def test_component_breakdown_missing_fields():
    """Test component breakdown with missing fields."""
    totals = {
        "net_bps": -1.0,
    }
    
    breakdown = compute_component_breakdown(totals)
    
    # Should use defaults for missing fields
    assert breakdown["gross_bps"] == 0.0
    assert breakdown["fees_eff_bps"] == 0.0
    assert breakdown["slippage_bps"] == 0.0
    assert breakdown["adverse_bps"] == 0.0
    assert breakdown["inventory_bps"] == 0.0
    assert breakdown["net_bps"] == -1.0


def test_neg_edge_drivers_positive_net_bps():
    """Test neg_edge_drivers with positive net_bps (should return empty)."""
    breakdown = {
        "gross_bps": 10.0,
        "fees_eff_bps": 2.0,
        "slippage_bps": 1.5,
        "adverse_bps": 2.5,
        "inventory_bps": 0.5,
        "net_bps": 3.5,  # Positive
    }
    
    drivers = compute_neg_edge_drivers(breakdown)
    
    # Should be empty for positive net_bps
    assert drivers == []


def test_neg_edge_drivers_negative_net_bps():
    """Test neg_edge_drivers with negative net_bps."""
    breakdown = {
        "gross_bps": 5.0,
        "fees_eff_bps": 2.0,
        "slippage_bps": 3.5,  # Largest contributor
        "adverse_bps": 2.5,   # Second largest
        "inventory_bps": 0.5,
        "net_bps": -3.5,      # Negative
    }
    
    drivers = compute_neg_edge_drivers(breakdown)
    
    # Should return top-2 contributors (by absolute value)
    assert len(drivers) == 2
    assert drivers[0] == "slippage_bps"  # Largest (3.5)
    assert drivers[1] == "adverse_bps"   # Second (2.5)


def test_neg_edge_drivers_equal_contributors():
    """Test neg_edge_drivers with equal contributors."""
    breakdown = {
        "gross_bps": 5.0,
        "fees_eff_bps": 3.0,
        "slippage_bps": 3.0,
        "adverse_bps": 2.0,
        "inventory_bps": 1.0,
        "net_bps": -4.0,
    }
    
    drivers = compute_neg_edge_drivers(breakdown)
    
    # Should return top-2 (order may vary for equal values)
    assert len(drivers) == 2
    assert "fees_eff_bps" in drivers or "slippage_bps" in drivers
    assert drivers[0] in ["fees_eff_bps", "slippage_bps"]


def test_block_reasons_no_audit_data():
    """Test block_reasons with no audit data."""
    audit_data = []
    
    reasons = compute_block_reasons(audit_data)
    
    assert reasons["min_interval"]["count"] == 0
    assert reasons["min_interval"]["ratio"] == 0.0
    assert reasons["concurrency"]["count"] == 0
    assert reasons["concurrency"]["ratio"] == 0.0
    assert reasons["risk"]["count"] == 0
    assert reasons["risk"]["ratio"] == 0.0
    assert reasons["throttle"]["count"] == 0
    assert reasons["throttle"]["ratio"] == 0.0


def test_block_reasons_with_audit_data():
    """Test block_reasons with audit data."""
    audit_data = [
        {"action": "PLACE", "blocked_reason": "min_interval"},
        {"action": "PLACE", "blocked_reason": "min_interval"},
        {"action": "PLACE", "blocked_reason": "concurrency"},
        {"action": "PLACE", "blocked_reason": "risk"},
        {"action": "PLACE", "blocked_reason": "min_interval"},
        {"action": "PLACE", "blocked_reason": "throttle"},
    ]
    
    reasons = compute_block_reasons(audit_data)
    
    # 3 min_interval, 1 concurrency, 1 risk, 1 throttle (total 6)
    assert reasons["min_interval"]["count"] == 3
    assert reasons["min_interval"]["ratio"] == pytest.approx(0.5, abs=0.01)
    assert reasons["concurrency"]["count"] == 1
    assert reasons["concurrency"]["ratio"] == pytest.approx(0.1667, abs=0.01)
    assert reasons["risk"]["count"] == 1
    assert reasons["risk"]["ratio"] == pytest.approx(0.1667, abs=0.01)
    assert reasons["throttle"]["count"] == 1
    assert reasons["throttle"]["ratio"] == pytest.approx(0.1667, abs=0.01)


def test_block_reasons_only_min_interval():
    """Test block_reasons with only min_interval blocks."""
    audit_data = [
        {"action": "PLACE", "blocked_reason": "min_interval"},
        {"action": "PLACE", "blocked_reason": "min_interval"},
        {"action": "PLACE", "blocked_reason": "min_interval"},
    ]
    
    reasons = compute_block_reasons(audit_data)
    
    assert reasons["min_interval"]["count"] == 3
    assert reasons["min_interval"]["ratio"] == 1.0
    assert reasons["concurrency"]["count"] == 0
    assert reasons["concurrency"]["ratio"] == 0.0
    assert reasons["risk"]["count"] == 0
    assert reasons["risk"]["ratio"] == 0.0
    assert reasons["throttle"]["count"] == 0
    assert reasons["throttle"]["ratio"] == 0.0


def test_block_reasons_unknown_reason_ignored():
    """Test block_reasons ignores unknown blocked_reason values."""
    audit_data = [
        {"action": "PLACE", "blocked_reason": "min_interval"},
        {"action": "PLACE", "blocked_reason": "unknown_reason"},  # Should be ignored
        {"action": "PLACE", "blocked_reason": "concurrency"},
    ]
    
    reasons = compute_block_reasons(audit_data)
    
    # Total should be 2 (unknown_reason ignored)
    assert reasons["min_interval"]["count"] == 1
    assert reasons["min_interval"]["ratio"] == pytest.approx(0.5, abs=0.01)
    assert reasons["concurrency"]["count"] == 1
    assert reasons["concurrency"]["ratio"] == pytest.approx(0.5, abs=0.01)


if __name__ == '__main__':
    pytest.main([__file__, "-v"])


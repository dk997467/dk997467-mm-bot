#!/usr/bin/env python3
"""
Unit tests for edge_metrics module.

Tests computation of extended edge metrics from mock inputs.
"""

import json
import pytest
from pathlib import Path

# Import module under test
import sys
sys.path.insert(0, str(Path(__file__).parents[2]))

from tools.reports.edge_metrics import (
    compute_edge_metrics,
    compute_p95_metric,
    compute_replace_ratio,
    compute_cancel_ratio,
    compute_blocked_ratios,
    calculate_percentile
)


def test_calculate_percentile():
    """Test percentile calculation."""
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    
    # P50 (median) - rounds up to idx 5 (value 6)
    assert calculate_percentile(values, 0.50) == 6
    
    # P95
    assert calculate_percentile(values, 0.95) == 10
    
    # P99
    assert calculate_percentile(values, 0.99) == 10
    
    # Empty list
    assert calculate_percentile([], 0.95) == 0.0


def test_compute_p95_metric_from_dist():
    """Test P95 computation from distribution."""
    data = {
        "adverse_bps_dist": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    }
    
    p95 = compute_p95_metric(data, "adverse_bps")
    assert p95 == 10.0


def test_compute_p95_metric_from_p95_key():
    """Test P95 computation from direct p95 key."""
    data = {
        "adverse_bps_p95": 5.5
    }
    
    p95 = compute_p95_metric(data, "adverse_bps")
    assert p95 == 5.5


def test_compute_p95_metric_fallback():
    """Test P95 computation fallback to max/value."""
    # Fallback to max
    data = {
        "adverse_bps_max": 7.0
    }
    p95 = compute_p95_metric(data, "adverse_bps")
    assert p95 == 7.0
    
    # Fallback to value itself
    data = {
        "adverse_bps": 3.0
    }
    p95 = compute_p95_metric(data, "adverse_bps")
    assert p95 == 3.0
    
    # No data
    data = {}
    p95 = compute_p95_metric(data, "adverse_bps")
    assert p95 == 0.0


def test_compute_replace_ratio():
    """Test replace ratio calculation."""
    audit_data = [
        {"action": "PLACE"},
        {"action": "REPLACE"},
        {"action": "REPLACE"},
        {"action": "CANCEL"},
    ]
    
    ratio = compute_replace_ratio(audit_data)
    assert ratio == 0.5  # 2 / 4
    
    # Empty audit
    assert compute_replace_ratio([]) == 0.0


def test_compute_cancel_ratio():
    """Test cancel ratio calculation."""
    audit_data = [
        {"action": "PLACE"},
        {"action": "PLACE"},
        {"action": "CANCEL"},
    ]
    
    ratio = compute_cancel_ratio(audit_data)
    assert ratio == pytest.approx(0.333, rel=0.01)  # 1 / 3
    
    # Empty audit
    assert compute_cancel_ratio([]) == 0.0


def test_compute_blocked_ratios_from_audit():
    """Test blocked ratios from audit data."""
    audit_data = [
        {"blocked_reason": "min_interval"},
        {"blocked_reason": "min_interval"},
        {"blocked_reason": "concurrency"},
        {"blocked_reason": "risk"},
    ]
    
    ratios = compute_blocked_ratios(audit_data, {})
    
    assert ratios["min_interval"] == 0.5  # 2 / 4
    assert ratios["concurrency"] == 0.25  # 1 / 4
    assert ratios["risk"] == 0.25  # 1 / 4
    assert ratios["throttle"] == 0.0


def test_compute_blocked_ratios_from_totals():
    """Test blocked ratios from totals (fallback)."""
    totals = {
        "blocked_by": {
            "min_interval": 0.6,
            "concurrency": 0.2,
            "risk": 0.1,
            "throttle": 0.1,
        }
    }
    
    ratios = compute_blocked_ratios([], totals)
    
    assert ratios["min_interval"] == 0.6
    assert ratios["concurrency"] == 0.2
    assert ratios["risk"] == 0.1
    assert ratios["throttle"] == 0.1


def test_compute_blocked_ratios_default():
    """Test blocked ratios default (all zeros)."""
    ratios = compute_blocked_ratios([], {})
    
    assert ratios["min_interval"] == 0.0
    assert ratios["concurrency"] == 0.0
    assert ratios["risk"] == 0.0
    assert ratios["throttle"] == 0.0


def test_compute_edge_metrics_structure():
    """Test that compute_edge_metrics returns correct structure."""
    inputs = {
        "edge_report": {
            "total": {
                "net_bps": 3.5,
                "gross_bps": 5.0,
                "fees_bps": 1.2,
                "inventory_bps": 0.3,
                "maker_share": 0.92,
            }
        },
        "audit": [],
        "metrics": {}
    }
    
    result = compute_edge_metrics(inputs)
    
    # Check top-level structure
    assert "totals" in result
    assert "symbols" in result
    assert "runtime" in result
    
    # Check totals structure
    totals = result["totals"]
    assert "net_bps" in totals
    assert "gross_bps" in totals
    assert "adverse_bps_p95" in totals
    assert "slippage_bps_p95" in totals
    assert "fees_eff_bps" in totals
    assert "inventory_bps" in totals
    assert "order_age_p95_ms" in totals
    assert "ws_lag_p95_ms" in totals
    assert "replace_ratio" in totals
    assert "cancel_ratio" in totals
    assert "blocked_ratio" in totals
    assert "maker_share_pct" in totals
    
    # Check values
    assert totals["net_bps"] == 3.5
    assert totals["gross_bps"] == 5.0
    assert totals["fees_eff_bps"] == 1.2
    assert totals["inventory_bps"] == 0.3
    assert totals["maker_share_pct"] == 92.0  # 0.92 * 100
    
    # Check runtime
    assert "utc" in result["runtime"]
    assert "version" in result["runtime"]


def test_compute_edge_metrics_with_audit():
    """Test metrics computation with audit data."""
    inputs = {
        "edge_report": {
            "total": {
                "net_bps": 2.5,
                "gross_bps": 4.0,
                "maker_share": 0.88,
            }
        },
        "audit": [
            {"action": "PLACE"},
            {"action": "REPLACE"},
            {"action": "CANCEL"},
            {"blocked_reason": "min_interval"},
        ],
        "metrics": {}
    }
    
    result = compute_edge_metrics(inputs)
    totals = result["totals"]
    
    # Check ratio calculations
    assert totals["replace_ratio"] == pytest.approx(0.333, rel=0.01)  # 1/3
    assert totals["cancel_ratio"] == pytest.approx(0.333, rel=0.01)  # 1/3
    
    # Check blocked ratios (only min_interval should be 1.0 since it's the only block)
    assert totals["blocked_ratio"]["min_interval"] == 1.0


def test_compute_edge_metrics_per_symbol():
    """Test per-symbol metrics computation."""
    inputs = {
        "edge_report": {
            "total": {
                "net_bps": 3.0,
                "maker_share": 0.90,
            },
            "symbols": {
                "BTCUSDT": {
                    "net_bps": 3.5,
                    "gross_bps": 5.0,
                    "maker_share": 0.93,
                },
                "ETHUSDT": {
                    "net_bps": 2.5,
                    "gross_bps": 4.0,
                    "maker_share": 0.87,
                }
            }
        },
        "audit": [],
        "metrics": {}
    }
    
    result = compute_edge_metrics(inputs)
    symbols = result["symbols"]
    
    # Check we have both symbols
    assert "BTCUSDT" in symbols
    assert "ETHUSDT" in symbols
    
    # Check BTCUSDT
    btc = symbols["BTCUSDT"]
    assert btc["net_bps"] == 3.5
    assert btc["gross_bps"] == 5.0
    assert btc["maker_share_pct"] == 93.0
    
    # Check ETHUSDT
    eth = symbols["ETHUSDT"]
    assert eth["net_bps"] == 2.5
    assert eth["gross_bps"] == 4.0
    assert eth["maker_share_pct"] == 87.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


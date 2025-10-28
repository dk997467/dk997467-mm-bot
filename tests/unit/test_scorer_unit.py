#!/usr/bin/env python3
"""
Unit tests for tools/backtest/scorer.py

Tests pure function:
    - aggregate_scores
"""

import pytest
from tools.backtest.scorer import aggregate_scores


# ======================================================================
# Test aggregate_scores
# ======================================================================


def test_aggregate_scores_single_symbol():
    """Test aggregation with single symbol."""
    per_symbol = {
        "BTCUSDT": {
            "gross_bps": 2.5,
            "fees_bps": 0.5,
            "taker_share_pct": 10.0,
            "order_age_p95_ms": 300.0
        }
    }
    
    result = aggregate_scores(per_symbol)
    
    # With single symbol, result should match input
    assert result["gross_bps"] == 2.5
    assert result["fees_bps"] == 0.5
    assert result["net_bps"] == 2.0  # gross - fees
    assert result["taker_share_pct"] == 10.0
    assert result["order_age_p95_ms"] == 300.0


def test_aggregate_scores_multiple_symbols():
    """Test aggregation with multiple symbols (averaging)."""
    per_symbol = {
        "BTCUSDT": {
            "gross_bps": 3.0,
            "fees_bps": 0.5,
            "taker_share_pct": 10.0,
            "order_age_p95_ms": 300.0
        },
        "ETHUSDT": {
            "gross_bps": 2.0,
            "fees_bps": 0.5,
            "taker_share_pct": 15.0,
            "order_age_p95_ms": 400.0
        }
    }
    
    result = aggregate_scores(per_symbol)
    
    # Averages: gross=(3.0+2.0)/2=2.5, fees=(0.5+0.5)/2=0.5, net=2.5-0.5=2.0
    assert result["gross_bps"] == 2.5
    assert result["fees_bps"] == 0.5
    assert result["net_bps"] == 2.0
    assert result["taker_share_pct"] == 12.5
    assert result["order_age_p95_ms"] == 350.0


def test_aggregate_scores_empty_dict():
    """Test with empty per_symbol dict."""
    result = aggregate_scores({})
    
    # Should return all zeros
    assert result["gross_bps"] == 0.0
    assert result["fees_bps"] == 0.0
    assert result["net_bps"] == 0.0
    assert result["taker_share_pct"] == 0.0
    assert result["order_age_p95_ms"] == 0.0


def test_aggregate_scores_sorted_keys():
    """Test that aggregation uses sorted keys (deterministic)."""
    per_symbol = {
        "ZECUSDT": {"gross_bps": 1.0, "fees_bps": 0.1, "taker_share_pct": 10.0, "order_age_p95_ms": 200.0},
        "BTCUSDT": {"gross_bps": 3.0, "fees_bps": 0.3, "taker_share_pct": 15.0, "order_age_p95_ms": 300.0},
        "ETHUSDT": {"gross_bps": 2.0, "fees_bps": 0.2, "taker_share_pct": 12.0, "order_age_p95_ms": 250.0},
    }
    
    result1 = aggregate_scores(per_symbol)
    result2 = aggregate_scores(per_symbol)
    
    # Should be deterministic
    assert result1 == result2
    
    # Average: (1.0+3.0+2.0)/3 = 2.0, (0.1+0.3+0.2)/3 = 0.2, net = 1.8
    assert result1["gross_bps"] == 2.0
    assert result1["fees_bps"] == 0.2
    assert result1["net_bps"] == 1.8


def test_aggregate_scores_net_bps_calculation():
    """Test that net_bps = gross_bps - fees_bps."""
    per_symbol = {
        "BTCUSDT": {"gross_bps": 5.0, "fees_bps": 1.5, "taker_share_pct": 10.0, "order_age_p95_ms": 300.0}
    }
    
    result = aggregate_scores(per_symbol)
    
    assert result["net_bps"] == 3.5  # 5.0 - 1.5


def test_aggregate_scores_precision():
    """Test that results are rounded to 12 decimal places."""
    per_symbol = {
        "BTCUSDT": {
            "gross_bps": 1.1234567890123456,  # More than 12 decimals
            "fees_bps": 0.1,
            "taker_share_pct": 10.0,
            "order_age_p95_ms": 300.0
        }
    }
    
    result = aggregate_scores(per_symbol)
    
    # Should be rounded to 12 decimals
    assert result["gross_bps"] == 1.123456789012


def test_aggregate_scores_type_conversion():
    """Test that all values are converted to floats."""
    per_symbol = {
        "BTCUSDT": {
            "gross_bps": "2.5",  # String
            "fees_bps": 0.5,
            "taker_share_pct": 10,  # Integer
            "order_age_p95_ms": 300.0
        }
    }
    
    result = aggregate_scores(per_symbol)
    
    # Should convert to float and calculate correctly
    assert isinstance(result["gross_bps"], float)
    assert result["gross_bps"] == 2.5
    assert isinstance(result["taker_share_pct"], float)
    assert result["taker_share_pct"] == 10.0


def test_aggregate_scores_three_symbols():
    """Test with three symbols."""
    per_symbol = {
        "BTCUSDT": {"gross_bps": 3.0, "fees_bps": 0.5, "taker_share_pct": 10.0, "order_age_p95_ms": 300.0},
        "ETHUSDT": {"gross_bps": 2.0, "fees_bps": 0.5, "taker_share_pct": 15.0, "order_age_p95_ms": 400.0},
        "BNBUSDT": {"gross_bps": 1.5, "fees_bps": 0.3, "taker_share_pct": 12.0, "order_age_p95_ms": 250.0},
    }
    
    result = aggregate_scores(per_symbol)
    
    # Averages: gross=(3+2+1.5)/3=2.166..., fees=(0.5+0.5+0.3)/3=0.433..., net=1.733...
    assert abs(result["gross_bps"] - 2.166666666667) < 1e-10
    assert abs(result["fees_bps"] - 0.433333333333) < 1e-10
    assert abs(result["net_bps"] - 1.733333333333) < 1e-10
    assert abs(result["taker_share_pct"] - 12.333333333333) < 1e-10
    assert abs(result["order_age_p95_ms"] - 316.666666666667) < 1e-10


# ======================================================================
# Run tests
# ======================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


#!/usr/bin/env python3
"""
Unit tests for tools/edge_cli.py

Tests pure functions:
    - _agg_symbols (from edge_audit, imported for aggregation)
    - _calc_totals
    - _render_md
"""

import pytest
from tools.edge_audit import _agg_symbols
from tools.edge_cli import _calc_totals, _render_md


# ======================================================================
# Test _agg_symbols (from edge_audit)
# ======================================================================


def test_agg_symbols_single_symbol():
    """Test aggregation with single symbol."""
    trades = [
        {
            "symbol": "BTCUSDT",
            "side": "B",
            "price": 50000.0,
            "qty": 0.1,
            "mid_before": 49990.0,
            "mid_after_1s": 50000.0,
            "fee_bps": 0.5,
            "ts_ms": 1000
        }
    ]
    
    result = _agg_symbols(trades)
    
    assert "BTCUSDT" in result
    assert "net_bps" in result["BTCUSDT"]
    assert "fills" in result["BTCUSDT"]
    assert result["BTCUSDT"]["fills"] == 1.0


def test_agg_symbols_multiple_symbols():
    """Test aggregation with multiple symbols."""
    trades = [
        {"symbol": "BTCUSDT", "side": "B", "price": 50000.0, "qty": 0.1, 
         "mid_before": 49990.0, "mid_after_1s": 50000.0, "fee_bps": 0.5, "ts_ms": 1000},
        {"symbol": "ETHUSDT", "side": "S", "price": 3000.0, "qty": 1.0, 
         "mid_before": 3005.0, "mid_after_1s": 3000.0, "fee_bps": 0.5, "ts_ms": 2000},
    ]
    
    result = _agg_symbols(trades)
    
    assert len(result) == 2
    assert "BTCUSDT" in result
    assert "ETHUSDT" in result


def test_agg_symbols_side_signs():
    """Test that side signs affect calculations correctly."""
    trades = [
        {"symbol": "BTCUSDT", "side": "B", "price": 50100.0, "qty": 0.1, 
         "mid_before": 50000.0, "mid_after_1s": 50050.0, "fee_bps": 0.5, "ts_ms": 1000},
        {"symbol": "BTCUSDT", "side": "S", "price": 49900.0, "qty": 0.1, 
         "mid_before": 50000.0, "mid_after_1s": 49950.0, "fee_bps": 0.5, "ts_ms": 2000},
    ]
    
    result = _agg_symbols(trades)
    
    # Both trades should contribute to fills
    assert result["BTCUSDT"]["fills"] == 2.0
    
    # Fees should always be negative
    assert result["BTCUSDT"]["fees_eff_bps"] < 0


def test_agg_symbols_fees_always_negative():
    """Test that fees are always negative (cost)."""
    trades = [
        {"symbol": "BTCUSDT", "side": "B", "price": 50000.0, "qty": 0.1, 
         "mid_before": 49990.0, "mid_after_1s": 50000.0, "fee_bps": 1.0, "ts_ms": 1000},
        {"symbol": "BTCUSDT", "side": "S", "price": 50000.0, "qty": 0.1, 
         "mid_before": 50010.0, "mid_after_1s": 50000.0, "fee_bps": 2.0, "ts_ms": 2000},
    ]
    
    result = _agg_symbols(trades)
    
    # Fees should be average of -1.0 and -2.0 = -1.5
    assert result["BTCUSDT"]["fees_eff_bps"] == -1.5


def test_agg_symbols_empty_input():
    """Test with empty trades list."""
    result = _agg_symbols([])
    assert result == {}


def test_agg_symbols_missing_symbol():
    """Test with trade missing symbol key."""
    trades = [
        {"side": "B", "price": 50000.0, "qty": 0.1, "mid_before": 49990.0}
    ]
    
    result = _agg_symbols(trades)
    assert result == {}


def test_agg_symbols_turnover_calculation():
    """Test turnover calculation (price * qty)."""
    trades = [
        {"symbol": "BTCUSDT", "side": "B", "price": 50000.0, "qty": 0.1, 
         "mid_before": 49990.0, "mid_after_1s": 50000.0, "fee_bps": 0.5, "ts_ms": 1000},
        {"symbol": "BTCUSDT", "side": "S", "price": 50100.0, "qty": 0.2, 
         "mid_before": 50110.0, "mid_after_1s": 50100.0, "fee_bps": 0.5, "ts_ms": 2000},
    ]
    
    result = _agg_symbols(trades)
    
    # Turnover = 50000*0.1 + 50100*0.2 = 5000 + 10020 = 15020
    assert result["BTCUSDT"]["turnover_usd"] == 15020.0


# ======================================================================
# Test _calc_totals
# ======================================================================


def test_calc_totals_single_symbol():
    """Test totals calculation with single symbol."""
    symbols_data = {
        "BTCUSDT": {
            "gross_bps": 2.0,
            "fees_eff_bps": -0.5,
            "adverse_bps": 0.1,
            "slippage_bps": -0.2,
            "inventory_bps": -0.3,
            "net_bps": 1.0,
            "fills": 10.0,
            "turnover_usd": 10000.0
        }
    }
    
    totals = _calc_totals(symbols_data)
    
    # With single symbol, totals should match symbol values
    assert totals["gross_bps"] == 2.0
    assert totals["fees_eff_bps"] == -0.5
    assert totals["net_bps"] == 1.0
    assert totals["fills"] == 10.0
    assert totals["turnover_usd"] == 10000.0


def test_calc_totals_multiple_symbols():
    """Test totals calculation with multiple symbols (weighted by turnover)."""
    symbols_data = {
        "BTCUSDT": {
            "gross_bps": 2.0,
            "fees_eff_bps": -0.5,
            "adverse_bps": 0.0,
            "slippage_bps": 0.0,
            "inventory_bps": 0.0,
            "net_bps": 1.5,
            "fills": 10.0,
            "turnover_usd": 5000.0  # 50% weight
        },
        "ETHUSDT": {
            "gross_bps": 4.0,
            "fees_eff_bps": -1.0,
            "adverse_bps": 0.0,
            "slippage_bps": 0.0,
            "inventory_bps": 0.0,
            "net_bps": 3.0,
            "fills": 20.0,
            "turnover_usd": 5000.0  # 50% weight
        }
    }
    
    totals = _calc_totals(symbols_data)
    
    # Weighted averages: gross = (2*5000 + 4*5000) / 10000 = 3.0
    assert totals["gross_bps"] == 3.0
    
    # fees = (-0.5*5000 + -1.0*5000) / 10000 = -0.75
    assert totals["fees_eff_bps"] == -0.75
    
    # net = (1.5*5000 + 3.0*5000) / 10000 = 2.25
    assert totals["net_bps"] == 2.25
    
    # Fills and turnover are summed
    assert totals["fills"] == 30.0
    assert totals["turnover_usd"] == 10000.0


def test_calc_totals_empty_input():
    """Test with empty symbols data."""
    totals = _calc_totals({})
    
    # Should return all zeros with correct keys
    assert totals["gross_bps"] == 0.0
    assert totals["fees_eff_bps"] == 0.0
    assert totals["net_bps"] == 0.0
    assert totals["fills"] == 0.0
    assert totals["turnover_usd"] == 0.0


def test_calc_totals_zero_turnover():
    """Test with zero turnover."""
    symbols_data = {
        "BTCUSDT": {
            "gross_bps": 2.0,
            "fees_eff_bps": -0.5,
            "adverse_bps": 0.0,
            "slippage_bps": 0.0,
            "inventory_bps": 0.0,
            "net_bps": 1.5,
            "fills": 10.0,
            "turnover_usd": 0.0
        }
    }
    
    totals = _calc_totals(symbols_data)
    
    # With zero turnover, implementation returns early with all zeros
    assert totals["gross_bps"] == 0.0
    assert totals["fees_eff_bps"] == 0.0
    assert totals["net_bps"] == 0.0
    assert totals["fills"] == 0.0  # Early return includes fills=0
    assert totals["turnover_usd"] == 0.0


def test_calc_totals_key_order():
    """Test that output has correct key order (matches golden format)."""
    symbols_data = {
        "BTCUSDT": {
            "gross_bps": 2.0,
            "fees_eff_bps": -0.5,
            "adverse_bps": 0.0,
            "slippage_bps": 0.0,
            "inventory_bps": 0.0,
            "net_bps": 1.5,
            "fills": 10.0,
            "turnover_usd": 5000.0
        }
    }
    
    totals = _calc_totals(symbols_data)
    
    expected_keys = [
        "adverse_bps", "fees_eff_bps", "fills", "gross_bps",
        "inventory_bps", "net_bps", "slippage_bps", "turnover_usd"
    ]
    
    assert list(totals.keys()) == expected_keys


def test_calc_totals_missing_keys():
    """Test with missing keys in symbols data."""
    symbols_data = {
        "BTCUSDT": {
            "fills": 10.0,
            "turnover_usd": 5000.0
            # Missing other keys
        }
    }
    
    totals = _calc_totals(symbols_data)
    
    # Should handle missing keys gracefully with defaults
    assert totals["gross_bps"] == 0.0
    assert totals["fills"] == 10.0
    assert totals["turnover_usd"] == 5000.0


# ======================================================================
# Test _render_md
# ======================================================================


def test_render_md_basic_structure():
    """Test basic markdown structure."""
    report = {
        "runtime": {"utc": "2025-01-01T00:00:00Z"},
        "symbols": {},
        "total": {"net_bps": 0.0, "fills": 0.0, "turnover_usd": 0.0}
    }
    
    md = _render_md(report)
    
    # Check sections present
    assert "# Edge Audit Report" in md
    assert "## Symbols" in md
    assert "## Total" in md
    assert md.endswith("\n")  # Trailing newline


def test_render_md_runtime():
    """Test runtime rendering."""
    report = {
        "runtime": {"utc": "2025-12-31T23:59:59Z"},
        "symbols": {},
        "total": {"net_bps": 0.0, "fills": 0.0, "turnover_usd": 0.0}
    }
    
    md = _render_md(report)
    
    assert "**Runtime:** 2025-12-31T23:59:59Z" in md


def test_render_md_single_symbol():
    """Test rendering with single symbol."""
    report = {
        "runtime": {"utc": "2025-01-01T00:00:00Z"},
        "symbols": {
            "BTCUSDT": {"net_bps": 2.5, "fills": 10.0, "turnover_usd": 5000.0}
        },
        "total": {"net_bps": 2.5, "fills": 10.0, "turnover_usd": 5000.0}
    }
    
    md = _render_md(report)
    
    # Check symbol row
    assert "BTCUSDT" in md
    assert "2.50" in md  # net_bps formatted
    assert "10" in md  # fills formatted
    assert "5000.00" in md  # turnover formatted


def test_render_md_multiple_symbols_sorted():
    """Test that symbols are sorted alphabetically."""
    report = {
        "runtime": {"utc": "2025-01-01T00:00:00Z"},
        "symbols": {
            "ETHUSDT": {"net_bps": 3.0, "fills": 20.0, "turnover_usd": 6000.0},
            "BTCUSDT": {"net_bps": 2.5, "fills": 10.0, "turnover_usd": 5000.0},
            "BNBUSDT": {"net_bps": 1.5, "fills": 5.0, "turnover_usd": 2500.0}
        },
        "total": {"net_bps": 2.33, "fills": 35.0, "turnover_usd": 13500.0}
    }
    
    md = _render_md(report)
    
    # Check that symbols appear in sorted order
    btc_pos = md.find("BTCUSDT")
    bnb_pos = md.find("BNBUSDT")
    eth_pos = md.find("ETHUSDT")
    
    assert btc_pos > 0
    assert bnb_pos > 0
    assert eth_pos > 0
    assert bnb_pos < btc_pos < eth_pos  # Alphabetical order


def test_render_md_totals_section():
    """Test totals section rendering."""
    report = {
        "runtime": {"utc": "2025-01-01T00:00:00Z"},
        "symbols": {},
        "total": {"net_bps": 3.456, "fills": 123.0, "turnover_usd": 9876.54}
    }
    
    md = _render_md(report)
    
    # Check total values formatted correctly
    assert "**Net BPS:** 3.46" in md  # 2 decimal places
    assert "**Fills:** 123" in md  # 0 decimal places
    assert "**Turnover USD:** 9876.54" in md  # 2 decimal places


def test_render_md_missing_keys():
    """Test rendering with missing keys (should default to 0)."""
    report = {
        "runtime": {"utc": "2025-01-01T00:00:00Z"},
        "symbols": {
            "BTCUSDT": {}  # Empty data
        },
        "total": {}  # Empty totals
    }
    
    md = _render_md(report)
    
    # Should render with default 0 values
    assert "BTCUSDT" in md
    assert "0.00" in md


def test_render_md_trailing_newline():
    """Test that output ends with newline (may have double newline before final)."""
    report = {
        "runtime": {"utc": "2025-01-01T00:00:00Z"},
        "symbols": {},
        "total": {"net_bps": 0.0, "fills": 0.0, "turnover_usd": 0.0}
    }
    
    md = _render_md(report)
    
    # Output ends with newline (implementation has "\n\n" from section structure)
    assert md.endswith("\n")


def test_render_md_deterministic_output():
    """Test that output is deterministic (same input = same output)."""
    report = {
        "runtime": {"utc": "2025-01-01T00:00:00Z"},
        "symbols": {
            "BTCUSDT": {"net_bps": 2.5, "fills": 10.0, "turnover_usd": 5000.0},
            "ETHUSDT": {"net_bps": 3.0, "fills": 20.0, "turnover_usd": 6000.0}
        },
        "total": {"net_bps": 2.75, "fills": 30.0, "turnover_usd": 11000.0}
    }
    
    md1 = _render_md(report)
    md2 = _render_md(report)
    
    assert md1 == md2


def test_render_md_empty_symbols():
    """Test rendering with no symbols."""
    report = {
        "runtime": {"utc": "2025-01-01T00:00:00Z"},
        "symbols": {},
        "total": {"net_bps": 0.0, "fills": 0.0, "turnover_usd": 0.0}
    }
    
    md = _render_md(report)
    
    # Should still have table header
    assert "| Symbol | Net BPS | Fills | Turnover USD |" in md
    assert "## Total" in md


# ======================================================================
# Run tests
# ======================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


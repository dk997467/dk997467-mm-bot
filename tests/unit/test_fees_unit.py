"""Unit tests for fees.py - Decimal-based fees/rebates calculation."""

import pytest
from decimal import Decimal

from tools.live.fees import (
    FeeSchedule,
    Fill,
    calc_fees_and_rebates,
    format_fees_report,
)


def test_fee_schedule_initialization():
    """Test FeeSchedule initialization with Decimal conversion."""
    schedule = FeeSchedule(
        maker_bps=1.0,
        taker_bps=7.0,
        maker_rebate_bps=2.0,
    )
    
    assert schedule.maker_bps == Decimal("1.0")
    assert schedule.taker_bps == Decimal("7.0")
    assert schedule.maker_rebate_bps == Decimal("2.0")


def test_fill_initialization():
    """Test Fill initialization with Decimal conversion."""
    fill = Fill(
        symbol="BTCUSDT",
        side="BUY",
        qty=0.001,
        price=50000.0,
        is_maker=True,
    )
    
    assert fill.qty == Decimal("0.001")
    assert fill.price == Decimal("50000.0")
    assert fill.notional == Decimal("50.0")


def test_calc_fees_empty_fills():
    """Test fees calculation with empty fills list."""
    schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    result = calc_fees_and_rebates([], schedule)
    
    assert result["gross_notional"] == Decimal("0")
    assert result["maker_notional"] == Decimal("0")
    assert result["taker_notional"] == Decimal("0")
    assert result["maker_count"] == 0
    assert result["taker_count"] == 0
    assert result["fees_absolute"] == Decimal("0")
    assert result["rebates_absolute"] == Decimal("0")
    assert result["net_absolute"] == Decimal("0")
    assert result["fees_bps"] == Decimal("0")
    assert result["rebates_bps"] == Decimal("0")
    assert result["net_bps"] == Decimal("0")
    assert result["maker_taker_ratio"] == Decimal("0")


def test_calc_fees_maker_only():
    """Test fees calculation with maker-only fills."""
    schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    fills = [
        Fill(
            symbol="BTCUSDT",
            side="BUY",
            qty=Decimal("0.001"),
            price=Decimal("50000.0"),
            is_maker=True,
        ),
        Fill(
            symbol="BTCUSDT",
            side="SELL",
            qty=Decimal("0.001"),
            price=Decimal("50100.0"),
            is_maker=True,
        ),
    ]
    
    result = calc_fees_and_rebates(fills, schedule)
    
    # Notional: 0.001 * 50000 + 0.001 * 50100 = 50 + 50.1 = 100.1
    assert result["gross_notional"] == Decimal("100.1")
    assert result["maker_notional"] == Decimal("100.1")
    assert result["taker_notional"] == Decimal("0")
    assert result["maker_count"] == 2
    assert result["taker_count"] == 0
    
    # Fees: 100.1 * 1.0 / 10000 = 0.01001
    assert abs(result["fees_absolute"] - Decimal("0.01001")) < Decimal("0.00001")
    
    # Rebates: 100.1 * 2.0 / 10000 = 0.02002
    assert abs(result["rebates_absolute"] - Decimal("0.02002")) < Decimal("0.00001")
    
    # Net: fees - rebates = 0.01001 - 0.02002 = -0.01001 (negative = profit)
    assert abs(result["net_absolute"] - (Decimal("0.01001") - Decimal("0.02002"))) < Decimal("0.00001")
    
    # Maker/taker ratio: 100% maker
    assert result["maker_taker_ratio"] == Decimal("1.0")


def test_calc_fees_taker_only():
    """Test fees calculation with taker-only fills."""
    schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    fills = [
        Fill(
            symbol="BTCUSDT",
            side="BUY",
            qty=Decimal("0.001"),
            price=Decimal("50000.0"),
            is_maker=False,
        ),
    ]
    
    result = calc_fees_and_rebates(fills, schedule)
    
    # Notional: 0.001 * 50000 = 50
    assert result["gross_notional"] == Decimal("50")
    assert result["maker_notional"] == Decimal("0")
    assert result["taker_notional"] == Decimal("50")
    assert result["maker_count"] == 0
    assert result["taker_count"] == 1
    
    # Fees: 50 * 7.0 / 10000 = 0.035
    assert result["fees_absolute"] == Decimal("0.035")
    
    # Rebates: 0 (no maker fills)
    assert result["rebates_absolute"] == Decimal("0")
    
    # Net: fees - rebates = 0.035 - 0 = 0.035 (positive = cost)
    assert result["net_absolute"] == Decimal("0.035")
    
    # Maker/taker ratio: 0% maker
    assert result["maker_taker_ratio"] == Decimal("0")


def test_calc_fees_mixed():
    """Test fees calculation with mixed maker/taker fills."""
    schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    fills = [
        Fill(
            symbol="BTCUSDT",
            side="BUY",
            qty=Decimal("0.001"),
            price=Decimal("50000.0"),
            is_maker=True,
        ),
        Fill(
            symbol="BTCUSDT",
            side="SELL",
            qty=Decimal("0.001"),
            price=Decimal("50000.0"),
            is_maker=False,
        ),
    ]
    
    result = calc_fees_and_rebates(fills, schedule)
    
    # Notional: 0.001 * 50000 + 0.001 * 50000 = 50 + 50 = 100
    assert result["gross_notional"] == Decimal("100")
    assert result["maker_notional"] == Decimal("50")
    assert result["taker_notional"] == Decimal("50")
    assert result["maker_count"] == 1
    assert result["taker_count"] == 1
    
    # Maker/taker ratio: 50% maker
    assert result["maker_taker_ratio"] == Decimal("0.5")


def test_format_fees_report():
    """Test fees report formatting."""
    schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    fills = [
        Fill(
            symbol="BTCUSDT",
            side="BUY",
            qty=Decimal("0.001"),
            price=Decimal("50000.0"),
            is_maker=True,
        ),
    ]
    
    result = calc_fees_and_rebates(fills, schedule)
    report = format_fees_report(result)
    
    assert "Fees & Rebates Report" in report
    assert "Gross Notional:" in report
    assert "Maker/Taker Ratio:" in report


def test_calc_fees_zero_fee():
    """Test fees calculation with zero fee schedule."""
    schedule = FeeSchedule(
        maker_bps=Decimal("0"),
        taker_bps=Decimal("0"),
        maker_rebate_bps=Decimal("0"),
    )
    
    fills = [
        Fill(
            symbol="BTCUSDT",
            side="BUY",
            qty=Decimal("0.001"),
            price=Decimal("50000.0"),
            is_maker=True,
        ),
    ]
    
    result = calc_fees_and_rebates(fills, schedule)
    
    assert result["fees_absolute"] == Decimal("0")
    assert result["rebates_absolute"] == Decimal("0")
    assert result["net_absolute"] == Decimal("0")


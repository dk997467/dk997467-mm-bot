"""
Unit tests for P0.11 VIP fee profiles.

Tests per-symbol fee/rebate schedules, profile selection, and fallback behavior.
"""

from decimal import Decimal

import pytest

from tools.live.fees import FeeSchedule, Fill, calc_fees_and_rebates
from tools.live.fees_profiles import (
    FeeProfile,
    VIP0_PROFILE,
    VIP2_PROFILE,
    MM_TIER_A_PROFILE,
    get_profile_for_symbol,
    build_profile_map,
)


def test_fee_profile_creation():
    """Test FeeProfile dataclass creation."""
    profile = FeeProfile(
        symbol="BTCUSDT",
        maker_bps=Decimal("0.5"),
        taker_bps=Decimal("5.0"),
        maker_rebate_bps=Decimal("2.5"),
        tier_name="VIP2",
    )
    
    assert profile.symbol == "BTCUSDT"
    assert profile.maker_bps == Decimal("0.5")
    assert profile.taker_bps == Decimal("5.0")
    assert profile.maker_rebate_bps == Decimal("2.5")
    assert profile.tier_name == "VIP2"


def test_get_profile_for_symbol_exact_match():
    """Test exact symbol match."""
    profiles = {
        "BTCUSDT": VIP2_PROFILE,
        "*": VIP0_PROFILE,
    }
    
    profile = get_profile_for_symbol("BTCUSDT", profiles)
    assert profile is not None
    assert profile.tier_name == "VIP2"


def test_get_profile_for_symbol_wildcard():
    """Test wildcard fallback."""
    profiles = {
        "BTCUSDT": VIP2_PROFILE,
        "*": VIP0_PROFILE,
    }
    
    profile = get_profile_for_symbol("ETHUSDT", profiles)
    assert profile is not None
    assert profile.tier_name == "VIP0"


def test_get_profile_for_symbol_no_match():
    """Test no match returns None."""
    profiles = {
        "BTCUSDT": VIP2_PROFILE,
    }
    
    profile = get_profile_for_symbol("ETHUSDT", profiles)
    assert profile is None


def test_build_profile_map_vip2():
    """Test build_profile_map for VIP2."""
    profiles = build_profile_map("VIP2")
    
    assert "*" in profiles
    assert profiles["*"].tier_name == "VIP2"
    assert profiles["*"].maker_bps == Decimal("0.5")


def test_build_profile_map_mm_tier_a():
    """Test build_profile_map for MM_Tier_A."""
    profiles = build_profile_map("MM_Tier_A")
    
    assert "*" in profiles
    assert profiles["*"].tier_name == "MM_Tier_A"
    assert profiles["*"].maker_bps == Decimal("0.0")
    assert profiles["*"].maker_rebate_bps == Decimal("5.0")


def test_build_profile_map_unknown_tier():
    """Test build_profile_map with unknown tier raises ValueError."""
    with pytest.raises(ValueError, match="Unknown tier"):
        build_profile_map("UNKNOWN_TIER")


def test_calc_fees_with_profile_map_override():
    """Test calc_fees_and_rebates with profile_map overrides fee_schedule."""
    # Default schedule: maker=1.0, taker=7.0, rebate=2.0
    default_schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    # VIP2 profile for BTCUSDT: maker=0.5, taker=5.0, rebate=2.5
    profile_map = {
        "BTCUSDT": FeeProfile(
            symbol="BTCUSDT",
            maker_bps=Decimal("0.5"),
            taker_bps=Decimal("5.0"),
            maker_rebate_bps=Decimal("2.5"),
            tier_name="VIP2",
        )
    }
    
    fills = [
        Fill(
            symbol="BTCUSDT",
            side="buy",
            qty=Decimal("1.0"),
            price=Decimal("50000.0"),
            is_maker=True,
        )
    ]
    
    # Without profile_map: uses default schedule
    result_default = calc_fees_and_rebates(fills, default_schedule, profile_map=None)
    # maker_fees = 50000 * 1.0 / 10000 = 5.0
    # maker_rebates = 50000 * 2.0 / 10000 = 10.0
    assert result_default["fees_absolute"] == Decimal("5.0")
    assert result_default["rebates_absolute"] == Decimal("10.0")
    assert result_default["net_absolute"] == Decimal("-5.0")  # rebate > fees
    
    # With profile_map: uses VIP2 profile
    result_profile = calc_fees_and_rebates(fills, default_schedule, profile_map=profile_map)
    # maker_fees = 50000 * 0.5 / 10000 = 2.5
    # maker_rebates = 50000 * 2.5 / 10000 = 12.5
    assert result_profile["fees_absolute"] == Decimal("2.5")
    assert result_profile["rebates_absolute"] == Decimal("12.5")
    assert result_profile["net_absolute"] == Decimal("-10.0")  # rebate > fees


def test_calc_fees_with_profile_map_fallback():
    """Test calc_fees_and_rebates falls back to fee_schedule for unmapped symbols."""
    default_schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    # Profile map only for BTCUSDT
    profile_map = {
        "BTCUSDT": FeeProfile(
            symbol="BTCUSDT",
            maker_bps=Decimal("0.5"),
            taker_bps=Decimal("5.0"),
            maker_rebate_bps=Decimal("2.5"),
            tier_name="VIP2",
        )
    }
    
    fills = [
        # BTCUSDT uses profile
        Fill(
            symbol="BTCUSDT",
            side="buy",
            qty=Decimal("1.0"),
            price=Decimal("50000.0"),
            is_maker=True,
        ),
        # ETHUSDT falls back to default schedule
        Fill(
            symbol="ETHUSDT",
            side="sell",
            qty=Decimal("10.0"),
            price=Decimal("3000.0"),
            is_maker=True,
        ),
    ]
    
    result = calc_fees_and_rebates(fills, default_schedule, profile_map=profile_map)
    
    # BTCUSDT: 50000 * 0.5 / 10000 = 2.5 fees, 50000 * 2.5 / 10000 = 12.5 rebates
    # ETHUSDT: 30000 * 1.0 / 10000 = 3.0 fees, 30000 * 2.0 / 10000 = 6.0 rebates
    # Total fees = 2.5 + 3.0 = 5.5
    # Total rebates = 12.5 + 6.0 = 18.5
    assert result["fees_absolute"] == Decimal("5.5")
    assert result["rebates_absolute"] == Decimal("18.5")
    assert result["net_absolute"] == Decimal("-13.0")


def test_calc_fees_with_profile_map_wildcard():
    """Test calc_fees_and_rebates with wildcard profile."""
    default_schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    # Wildcard profile applies to all symbols
    profile_map = {
        "*": MM_TIER_A_PROFILE,
    }
    
    fills = [
        Fill(
            symbol="BTCUSDT",
            side="buy",
            qty=Decimal("1.0"),
            price=Decimal("50000.0"),
            is_maker=True,
        ),
        Fill(
            symbol="ETHUSDT",
            side="sell",
            qty=Decimal("10.0"),
            price=Decimal("3000.0"),
            is_maker=True,
        ),
    ]
    
    result = calc_fees_and_rebates(fills, default_schedule, profile_map=profile_map)
    
    # MM_Tier_A: maker_bps=0.0, rebate=5.0
    # BTCUSDT: 50000 * 0.0 / 10000 = 0.0 fees, 50000 * 5.0 / 10000 = 25.0 rebates
    # ETHUSDT: 30000 * 0.0 / 10000 = 0.0 fees, 30000 * 5.0 / 10000 = 15.0 rebates
    assert result["fees_absolute"] == Decimal("0.0")
    assert result["rebates_absolute"] == Decimal("40.0")
    assert result["net_absolute"] == Decimal("-40.0")


def test_calc_fees_with_profile_map_mixed_maker_taker():
    """Test calc_fees_and_rebates with mixed maker/taker fills and profiles."""
    default_schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    profile_map = {
        "BTCUSDT": VIP2_PROFILE,  # maker=0.5, taker=5.0, rebate=2.5
        "*": VIP0_PROFILE,  # maker=1.0, taker=7.0, rebate=0.0
    }
    
    fills = [
        # BTC maker (VIP2)
        Fill(
            symbol="BTCUSDT",
            side="buy",
            qty=Decimal("1.0"),
            price=Decimal("50000.0"),
            is_maker=True,
        ),
        # BTC taker (VIP2)
        Fill(
            symbol="BTCUSDT",
            side="sell",
            qty=Decimal("0.5"),
            price=Decimal("50100.0"),
            is_maker=False,
        ),
        # ETH maker (VIP0 wildcard)
        Fill(
            symbol="ETHUSDT",
            side="buy",
            qty=Decimal("10.0"),
            price=Decimal("3000.0"),
            is_maker=True,
        ),
    ]
    
    result = calc_fees_and_rebates(fills, default_schedule, profile_map=profile_map)
    
    # BTC maker: 50000 * 0.5 / 10000 = 2.5 fees, 50000 * 2.5 / 10000 = 12.5 rebates
    # BTC taker: 25050 * 5.0 / 10000 = 12.525 fees
    # ETH maker: 30000 * 1.0 / 10000 = 3.0 fees, 30000 * 0.0 / 10000 = 0.0 rebates
    # Total fees = 2.5 + 12.525 + 3.0 = 18.025
    # Total rebates = 12.5 + 0.0 = 12.5
    assert result["fees_absolute"] == Decimal("18.025")
    assert result["rebates_absolute"] == Decimal("12.5")
    assert result["net_absolute"] == Decimal("5.525")


def test_calc_fees_rounding_exactness_with_profiles():
    """Test Decimal exactness with per-symbol profiles."""
    default_schedule = FeeSchedule(
        maker_bps=Decimal("1.0"),
        taker_bps=Decimal("7.0"),
        maker_rebate_bps=Decimal("2.0"),
    )
    
    profile_map = {
        "BTCUSDT": FeeProfile(
            symbol="BTCUSDT",
            maker_bps=Decimal("0.333"),  # Non-round number
            taker_bps=Decimal("5.555"),
            maker_rebate_bps=Decimal("1.111"),
            tier_name="Custom",
        )
    }
    
    fills = [
        Fill(
            symbol="BTCUSDT",
            side="buy",
            qty=Decimal("1.234567"),
            price=Decimal("49999.99"),
            is_maker=True,
        )
    ]
    
    result = calc_fees_and_rebates(fills, default_schedule, profile_map=profile_map)
    
    # Notional = 1.234567 * 49999.99 = 61728.762876533
    # Fees = 61728.762876533 * 0.333 / 10000 = 2.05556779382653589
    # Rebates = 61728.762876533 * 1.111 / 10000 = 6.85800551082283963
    
    # Check exact Decimal arithmetic (no float rounding)
    assert isinstance(result["fees_absolute"], Decimal)
    assert isinstance(result["rebates_absolute"], Decimal)
    
    # Verify exact values
    expected_notional = Decimal("1.234567") * Decimal("49999.99")
    expected_fees = (expected_notional * Decimal("0.333")) / Decimal("10000")
    expected_rebates = (expected_notional * Decimal("1.111")) / Decimal("10000")
    
    assert result["fees_absolute"] == expected_fees
    assert result["rebates_absolute"] == expected_rebates


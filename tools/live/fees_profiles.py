"""
P0.11: VIP Fee Profiles — Per-symbol fee/rebate schedules

Supports different trading tiers or strategies with per-symbol fee profiles.
Falls back to CLI flags if no profile specified for a symbol.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FeeProfile:
    """
    Per-symbol fee profile for VIP tiers or custom strategies.
    
    Attributes:
        symbol: Trading pair (e.g., "BTCUSDT")
        maker_bps: Maker fee in basis points (positive = pay, negative = rebate)
        taker_bps: Taker fee in basis points (always positive)
        maker_rebate_bps: Maker rebate in basis points (positive = earn, overrides maker_bps if rebate active)
        tier_name: Human-readable tier name (e.g., "VIP1", "MM_Tier_A")
    
    Example:
        >>> profile = FeeProfile(
        ...     symbol="BTCUSDT",
        ...     maker_bps=Decimal("0.5"),
        ...     taker_bps=Decimal("5.0"),
        ...     maker_rebate_bps=Decimal("2.5"),
        ...     tier_name="VIP2"
        ... )
    """
    symbol: str
    maker_bps: Decimal
    taker_bps: Decimal
    maker_rebate_bps: Decimal
    tier_name: str


# Example VIP profiles (Bybit-like tiering)
# Ref: https://www.bybit.com/en/help-center/article/VIP-Program

VIP0_PROFILE = FeeProfile(
    symbol="*",  # Wildcard for all symbols
    maker_bps=Decimal("1.0"),
    taker_bps=Decimal("7.0"),
    maker_rebate_bps=Decimal("0.0"),
    tier_name="VIP0",
)

VIP1_PROFILE = FeeProfile(
    symbol="*",
    maker_bps=Decimal("0.8"),
    taker_bps=Decimal("6.5"),
    maker_rebate_bps=Decimal("1.0"),
    tier_name="VIP1",
)

VIP2_PROFILE = FeeProfile(
    symbol="*",
    maker_bps=Decimal("0.5"),
    taker_bps=Decimal("5.0"),
    maker_rebate_bps=Decimal("2.5"),
    tier_name="VIP2",
)

VIP3_PROFILE = FeeProfile(
    symbol="*",
    maker_bps=Decimal("0.2"),
    taker_bps=Decimal("4.0"),
    maker_rebate_bps=Decimal("3.0"),
    tier_name="VIP3",
)

MM_TIER_A_PROFILE = FeeProfile(
    symbol="*",
    maker_bps=Decimal("0.0"),  # No maker fee
    taker_bps=Decimal("3.0"),
    maker_rebate_bps=Decimal("5.0"),  # Strong rebate for MM
    tier_name="MM_Tier_A",
)


def get_profile_for_symbol(symbol: str, profiles: dict[str, FeeProfile]) -> FeeProfile | None:
    """
    Get fee profile for a symbol, with wildcard fallback.
    
    Args:
        symbol: Trading pair (e.g., "BTCUSDT")
        profiles: Dict mapping symbol -> FeeProfile
    
    Returns:
        FeeProfile if found, else None
    
    Priority:
        1. Exact match (e.g., profiles["BTCUSDT"])
        2. Wildcard match (e.g., profiles["*"])
        3. None (fallback to CLI flags)
    
    Example:
        >>> profiles = {
        ...     "BTCUSDT": VIP2_PROFILE,
        ...     "*": VIP1_PROFILE,
        ... }
        >>> get_profile_for_symbol("BTCUSDT", profiles)
        FeeProfile(symbol='BTCUSDT', maker_bps=Decimal('0.5'), ...)
        >>> get_profile_for_symbol("ETHUSDT", profiles)
        FeeProfile(symbol='*', maker_bps=Decimal('0.8'), ...)
        >>> get_profile_for_symbol("UNKNOWN", {})
        None
    """
    # Exact match
    if symbol in profiles:
        return profiles[symbol]
    
    # Wildcard fallback
    if "*" in profiles:
        return profiles["*"]
    
    return None


def build_profile_map(tier_name: str) -> dict[str, FeeProfile]:
    """
    Build a profile map for a given tier name (convenience helper).
    
    Args:
        tier_name: VIP tier or MM tier name (e.g., "VIP2", "MM_Tier_A")
    
    Returns:
        Dict mapping "*" -> FeeProfile for the specified tier
    
    Raises:
        ValueError: If tier_name not recognized
    
    Example:
        >>> profiles = build_profile_map("VIP2")
        >>> profiles["*"].maker_bps
        Decimal('0.5')
    """
    tier_map = {
        "VIP0": VIP0_PROFILE,
        "VIP1": VIP1_PROFILE,
        "VIP2": VIP2_PROFILE,
        "VIP3": VIP3_PROFILE,
        "MM_Tier_A": MM_TIER_A_PROFILE,
    }
    
    if tier_name not in tier_map:
        raise ValueError(f"Unknown tier: {tier_name}. Valid tiers: {list(tier_map.keys())}")
    
    return {"*": tier_map[tier_name]}


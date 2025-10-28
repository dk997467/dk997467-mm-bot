"""
Fees and rebates calculation for maker/taker fills.

Pure, deterministic, Decimal-based calculations for:
- Fee calculation (maker/taker)
- Rebate calculation (maker rebates)
- Net BPS (gross - fees + rebates)
- P0.11: Per-symbol VIP fee profiles support
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from tools.live.fees_profiles import FeeProfile


@dataclass
class FeeSchedule:
    """
    Fee schedule for maker/taker trades.
    
    All values in basis points (BPS).
    - maker_bps: Fee for maker orders (e.g., 1.0 BPS = 0.01%)
    - taker_bps: Fee for taker orders (e.g., 7.0 BPS = 0.07%)
    - maker_rebate_bps: Rebate for maker orders (positive, e.g., 2.0 BPS = 0.02%)
    
    Note: maker_rebate_bps is POSITIVE (represents income/rebate).
    """
    
    maker_bps: Decimal
    taker_bps: Decimal
    maker_rebate_bps: Decimal
    
    def __post_init__(self):
        """Ensure all values are Decimal."""
        if not isinstance(self.maker_bps, Decimal):
            object.__setattr__(self, "maker_bps", Decimal(str(self.maker_bps)))
        if not isinstance(self.taker_bps, Decimal):
            object.__setattr__(self, "taker_bps", Decimal(str(self.taker_bps)))
        if not isinstance(self.maker_rebate_bps, Decimal):
            object.__setattr__(self, "maker_rebate_bps", Decimal(str(self.maker_rebate_bps)))


@dataclass
class Fill:
    """
    Fill event with fee information.
    
    Attributes:
        symbol: Trading symbol
        side: BUY or SELL
        qty: Filled quantity
        price: Fill price
        is_maker: True if maker, False if taker
        fee_currency: Fee currency (e.g., USDT)
        fee_amount: Fee amount in fee_currency (can be negative for rebates)
    """
    
    symbol: str
    side: str
    qty: Decimal
    price: Decimal
    is_maker: bool
    fee_currency: str = "USDT"
    fee_amount: Decimal = Decimal("0")
    
    def __post_init__(self):
        """Ensure numeric values are Decimal."""
        if not isinstance(self.qty, Decimal):
            object.__setattr__(self, "qty", Decimal(str(self.qty)))
        if not isinstance(self.price, Decimal):
            object.__setattr__(self, "price", Decimal(str(self.price)))
        if not isinstance(self.fee_amount, Decimal):
            object.__setattr__(self, "fee_amount", Decimal(str(self.fee_amount)))
    
    @property
    def notional(self) -> Decimal:
        """Calculate notional value (qty * price)."""
        return self.qty * self.price


def calc_fees_and_rebates(
    fills: list[Fill],
    fee_schedule: FeeSchedule,
    profile_map: dict[str, "FeeProfile"] | None = None,
) -> dict[str, Any]:
    """
    Calculate fees and rebates for a list of fills.
    
    P0.11: Supports per-symbol VIP fee profiles. If profile_map is provided,
    per-symbol schedules are used; otherwise, fee_schedule is applied globally.
    
    Args:
        fills: List of Fill objects
        fee_schedule: Default FeeSchedule (used as fallback if no profile matches)
        profile_map: Optional dict mapping symbol -> FeeProfile (P0.11)
    
    Returns:
        Dictionary with:
        - gross_notional: Total notional value
        - maker_notional: Notional from maker fills
        - taker_notional: Notional from taker fills
        - maker_count: Number of maker fills
        - taker_count: Number of taker fills
        - fees_absolute: Total fees paid (positive)
        - rebates_absolute: Total rebates earned (positive)
        - net_absolute: Net cost (fees - rebates)
        - fees_bps: Fees as BPS of gross notional
        - rebates_bps: Rebates as BPS of gross notional
        - net_bps: Net as BPS of gross notional
        - maker_taker_ratio: Ratio of maker to total notional (0-1)
    """
    if not fills:
        return {
            "gross_notional": Decimal("0"),
            "maker_notional": Decimal("0"),
            "taker_notional": Decimal("0"),
            "maker_count": 0,
            "taker_count": 0,
            "fees_absolute": Decimal("0"),
            "rebates_absolute": Decimal("0"),
            "net_absolute": Decimal("0"),
            "fees_bps": Decimal("0"),
            "rebates_bps": Decimal("0"),
            "net_bps": Decimal("0"),
            "maker_taker_ratio": Decimal("0"),
        }
    
    # Aggregate notional
    maker_notional = Decimal("0")
    taker_notional = Decimal("0")
    maker_count = 0
    taker_count = 0
    
    for fill in fills:
        notional = fill.notional
        if fill.is_maker:
            maker_notional += notional
            maker_count += 1
        else:
            taker_notional += notional
            taker_count += 1
    
    gross_notional = maker_notional + taker_notional
    
    # P0.11: Calculate fees and rebates per-symbol if profile_map provided
    # Fees are positive (cost), Rebates are positive (income)
    maker_fees = Decimal("0")
    taker_fees = Decimal("0")
    maker_rebates = Decimal("0")
    
    if profile_map is not None:
        # Per-symbol calculation
        from tools.live.fees_profiles import get_profile_for_symbol
        
        for fill in fills:
            profile = get_profile_for_symbol(fill.symbol, profile_map)
            if profile is None:
                # Fallback to global fee_schedule
                profile_maker_bps = fee_schedule.maker_bps
                profile_taker_bps = fee_schedule.taker_bps
                profile_rebate_bps = fee_schedule.maker_rebate_bps
            else:
                profile_maker_bps = profile.maker_bps
                profile_taker_bps = profile.taker_bps
                profile_rebate_bps = profile.maker_rebate_bps
            
            notional = fill.notional
            if fill.is_maker:
                maker_fees += (notional * profile_maker_bps) / Decimal("10000")
                maker_rebates += (notional * profile_rebate_bps) / Decimal("10000")
            else:
                taker_fees += (notional * profile_taker_bps) / Decimal("10000")
    else:
        # Global calculation (original behavior)
        maker_fees = (maker_notional * fee_schedule.maker_bps) / Decimal("10000")
        taker_fees = (taker_notional * fee_schedule.taker_bps) / Decimal("10000")
        maker_rebates = (maker_notional * fee_schedule.maker_rebate_bps) / Decimal("10000")
    
    fees_absolute = maker_fees + taker_fees
    rebates_absolute = maker_rebates
    net_absolute = fees_absolute - rebates_absolute
    
    # Calculate BPS (relative to gross notional)
    if gross_notional > 0:
        fees_bps = (fees_absolute / gross_notional) * Decimal("10000")
        rebates_bps = (rebates_absolute / gross_notional) * Decimal("10000")
        net_bps = (net_absolute / gross_notional) * Decimal("10000")
        maker_taker_ratio = maker_notional / gross_notional
    else:
        fees_bps = Decimal("0")
        rebates_bps = Decimal("0")
        net_bps = Decimal("0")
        maker_taker_ratio = Decimal("0")
    
    return {
        "gross_notional": gross_notional,
        "maker_notional": maker_notional,
        "taker_notional": taker_notional,
        "maker_count": maker_count,
        "taker_count": taker_count,
        "fees_absolute": fees_absolute,
        "rebates_absolute": rebates_absolute,
        "net_absolute": net_absolute,
        "fees_bps": fees_bps,
        "rebates_bps": rebates_bps,
        "net_bps": net_bps,
        "maker_taker_ratio": maker_taker_ratio,
    }


def format_fees_report(result: dict[str, Any]) -> str:
    """
    Format fees calculation result as human-readable string.
    
    Args:
        result: Output from calc_fees_and_rebates()
    
    Returns:
        Formatted string report
    """
    lines = [
        "Fees & Rebates Report",
        "=" * 50,
        f"Gross Notional:     ${result['gross_notional']:.2f}",
        f"  Maker Notional:   ${result['maker_notional']:.2f} ({result['maker_count']} fills)",
        f"  Taker Notional:   ${result['taker_notional']:.2f} ({result['taker_count']} fills)",
        "",
        f"Fees:               ${result['fees_absolute']:.4f} ({result['fees_bps']:.2f} BPS)",
        f"Rebates:            ${result['rebates_absolute']:.4f} ({result['rebates_bps']:.2f} BPS)",
        f"Net Cost:           ${result['net_absolute']:.4f} ({result['net_bps']:.2f} BPS)",
        "",
        f"Maker/Taker Ratio:  {result['maker_taker_ratio']:.4f}",
    ]
    return "\n".join(lines)


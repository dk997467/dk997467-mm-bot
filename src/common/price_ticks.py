"""
Tick-safe price operations with integer-tick math.

Prevents floating-point drift and ensures all prices are exact multiples
of the exchange tick size.

Key features:
- Integer-tick arithmetic (no float drift)
- Directional rounding (floor for bids, ceil for asks)
- Clamp to prevent price spikes
- Decimal precision for I/O boundaries
- Property-based tested with Hypothesis
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP, InvalidOperation
from typing import Union

# Type aliases
Price = Union[Decimal, float, int]


class TickSizeError(ValueError):
    """Raised when tick size is invalid."""
    pass


class PriceError(ValueError):
    """Raised when price is invalid."""
    pass


def _to_decimal(value: Price) -> Decimal:
    """
    Convert value to Decimal safely.
    
    Args:
        value: Price value (Decimal, float, int, or string)
    
    Returns:
        Decimal value
    
    Raises:
        PriceError: If value is NaN, Inf, or invalid
    """
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, (int, str)):
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError) as e:
            raise PriceError(f"Invalid price value: {value}") from e
    elif isinstance(value, float):
        # Convert float to string first to avoid precision issues
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError) as e:
            raise PriceError(f"Invalid price value: {value}") from e
    else:
        raise PriceError(f"Unsupported price type: {type(value)}")
    
    # Check for NaN, Inf
    if decimal_value.is_nan():
        raise PriceError("Price cannot be NaN")
    if decimal_value.is_infinite():
        raise PriceError("Price cannot be infinite")
    
    return decimal_value


def _validate_tick_size(tick_size: Decimal) -> None:
    """
    Validate tick size.
    
    Args:
        tick_size: Tick size to validate
    
    Raises:
        TickSizeError: If tick size is invalid
    """
    if tick_size <= 0:
        raise TickSizeError(f"Tick size must be positive, got {tick_size}")
    
    if tick_size.is_nan():
        raise TickSizeError("Tick size cannot be NaN")
    
    if tick_size.is_infinite():
        raise TickSizeError("Tick size cannot be infinite")


def to_ticks(price: Price, tick_size: Price) -> int:
    """
    Convert price to integer number of ticks.
    
    Rounds to nearest integer (ROUND_HALF_UP).
    
    Args:
        price: Price value
        tick_size: Tick size (minimum price increment)
    
    Returns:
        Number of ticks as integer
    
    Raises:
        PriceError: If price is invalid
        TickSizeError: If tick_size is invalid
    
    Example:
        >>> to_ticks(Decimal('50000.5'), Decimal('0.5'))
        100001
        >>> to_ticks(Decimal('50000.0'), Decimal('0.5'))
        100000
    """
    price_dec = _to_decimal(price)
    tick_dec = _to_decimal(tick_size)
    _validate_tick_size(tick_dec)
    
    # Divide and round to nearest integer
    # Using ROUND_HALF_UP (round half away from zero)
    ticks_dec = (price_dec / tick_dec).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    
    return int(ticks_dec)


def from_ticks(ticks: int, tick_size: Price) -> Decimal:
    """
    Convert integer ticks to price.
    
    Args:
        ticks: Number of ticks (integer)
        tick_size: Tick size (minimum price increment)
    
    Returns:
        Price as Decimal (exact multiple of tick_size)
    
    Raises:
        TickSizeError: If tick_size is invalid
    
    Example:
        >>> from_ticks(100001, Decimal('0.5'))
        Decimal('50000.5')
        >>> from_ticks(100000, Decimal('0.5'))
        Decimal('50000.0')
    """
    tick_dec = _to_decimal(tick_size)
    _validate_tick_size(tick_dec)
    
    # Multiply: ticks * tick_size
    price = Decimal(ticks) * tick_dec
    
    return price


def floor_to_tick(price: Price, tick_size: Price) -> Decimal:
    """
    Round price DOWN to nearest tick (for bids).
    
    Always rounds towards negative infinity (floor).
    
    Args:
        price: Price to round
        tick_size: Tick size
    
    Returns:
        Price rounded down to nearest tick
    
    Example:
        >>> floor_to_tick(Decimal('50000.7'), Decimal('0.5'))
        Decimal('50000.5')
        >>> floor_to_tick(Decimal('50000.5'), Decimal('0.5'))
        Decimal('50000.5')
    """
    price_dec = _to_decimal(price)
    tick_dec = _to_decimal(tick_size)
    _validate_tick_size(tick_dec)
    
    # Divide, round down, multiply back
    ticks = (price_dec / tick_dec).quantize(Decimal('1'), rounding=ROUND_DOWN)
    floored = ticks * tick_dec
    
    return floored


def ceil_to_tick(price: Price, tick_size: Price) -> Decimal:
    """
    Round price UP to nearest tick (for asks).
    
    Always rounds towards positive infinity (ceil).
    
    Args:
        price: Price to round
        tick_size: Tick size
    
    Returns:
        Price rounded up to nearest tick
    
    Example:
        >>> ceil_to_tick(Decimal('50000.3'), Decimal('0.5'))
        Decimal('50000.5')
        >>> ceil_to_tick(Decimal('50000.5'), Decimal('0.5'))
        Decimal('50000.5')
    """
    price_dec = _to_decimal(price)
    tick_dec = _to_decimal(tick_size)
    _validate_tick_size(tick_dec)
    
    # Divide, round up, multiply back
    ticks = (price_dec / tick_dec).quantize(Decimal('1'), rounding=ROUND_UP)
    ceiled = ticks * tick_dec
    
    return ceiled


def round_to_tick(price: Price, tick_size: Price) -> Decimal:
    """
    Round price to nearest tick (ROUND_HALF_UP).
    
    Args:
        price: Price to round
        tick_size: Tick size
    
    Returns:
        Price rounded to nearest tick
    
    Example:
        >>> round_to_tick(Decimal('50000.7'), Decimal('0.5'))
        Decimal('50001.0')
        >>> round_to_tick(Decimal('50000.2'), Decimal('0.5'))
        Decimal('50000.0')
    """
    ticks = to_ticks(price, tick_size)
    return from_ticks(ticks, tick_size)


def clamp_to_mid(
    price: Price,
    mid: Price,
    k_ticks: int,
    tick_size: Price
) -> Decimal:
    """
    Clamp price to be within k_ticks of mid (anti-spike protection).
    
    Ensures: |price - mid| <= k_ticks * tick_size
    
    Args:
        price: Price to clamp
        mid: Mid price (center)
        k_ticks: Maximum distance in ticks
        tick_size: Tick size
    
    Returns:
        Clamped price (exact multiple of tick_size)
    
    Example:
        >>> clamp_to_mid(Decimal('50010'), Decimal('50000'), 5, Decimal('1'))
        Decimal('50005')
        >>> clamp_to_mid(Decimal('50003'), Decimal('50000'), 5, Decimal('1'))
        Decimal('50003')
    """
    price_dec = _to_decimal(price)
    mid_dec = _to_decimal(mid)
    tick_dec = _to_decimal(tick_size)
    _validate_tick_size(tick_dec)
    
    # Convert to ticks
    mid_ticks = to_ticks(mid_dec, tick_dec)
    price_ticks = to_ticks(price_dec, tick_dec)
    
    # Clamp distance
    max_distance = k_ticks
    distance = price_ticks - mid_ticks
    
    if distance > max_distance:
        clamped_ticks = mid_ticks + max_distance
    elif distance < -max_distance:
        clamped_ticks = mid_ticks - max_distance
    else:
        clamped_ticks = price_ticks
    
    return from_ticks(clamped_ticks, tick_dec)


def compute_bid_ask(
    mid: Price,
    spread_ticks: int,
    tick_size: Price,
    k_ticks: int = 5,
    min_spread_ticks: int = 1
) -> tuple[Decimal, Decimal]:
    """
    Compute tick-safe bid and ask prices from mid and spread.
    
    Guarantees:
    - bid <= mid <= ask (no cross-mid)
    - ask - bid >= min_spread_ticks * tick_size
    - Both prices are exact multiples of tick_size
    - Prices within k_ticks of mid (anti-spike)
    
    Args:
        mid: Mid price
        spread_ticks: Desired spread in ticks
        tick_size: Tick size
        k_ticks: Maximum distance from mid (clamp)
        min_spread_ticks: Minimum spread in ticks (default 1)
    
    Returns:
        (bid_price, ask_price) as Decimals
    
    Raises:
        ValueError: If inputs are invalid
    
    Example:
        >>> compute_bid_ask(Decimal('50000'), 2, Decimal('0.5'))
        (Decimal('49999.5'), Decimal('50000.5'))
    """
    mid_dec = _to_decimal(mid)
    tick_dec = _to_decimal(tick_size)
    _validate_tick_size(tick_dec)
    
    if spread_ticks < min_spread_ticks:
        spread_ticks = min_spread_ticks
    
    if k_ticks < 1:
        raise ValueError(f"k_ticks must be >= 1, got {k_ticks}")
    
    # Convert mid to ticks
    mid_ticks = to_ticks(mid_dec, tick_dec)
    
    # Compute raw bid/ask in ticks
    half_spread_ticks = spread_ticks // 2
    
    # Bid: floor(mid - half_spread)
    raw_bid_ticks = mid_ticks - half_spread_ticks
    
    # Ask: ceil(mid + half_spread)
    raw_ask_ticks = mid_ticks + half_spread_ticks
    
    # Ensure minimum spread
    if raw_ask_ticks - raw_bid_ticks < min_spread_ticks:
        # Widen spread symmetrically
        deficit = min_spread_ticks - (raw_ask_ticks - raw_bid_ticks)
        raw_bid_ticks -= (deficit + 1) // 2
        raw_ask_ticks += deficit // 2 + (deficit % 2)
    
    # Clamp to k_ticks from mid
    bid_ticks = max(raw_bid_ticks, mid_ticks - k_ticks)
    ask_ticks = min(raw_ask_ticks, mid_ticks + k_ticks)
    
    # Ensure spread still valid after clamp
    if ask_ticks - bid_ticks < min_spread_ticks:
        # If clamping violated spread, adjust symmetrically
        current_spread = ask_ticks - bid_ticks
        deficit = min_spread_ticks - current_spread
        
        # Try to widen
        if bid_ticks - deficit // 2 >= mid_ticks - k_ticks:
            bid_ticks -= deficit // 2
            ask_ticks += (deficit + 1) // 2
        elif ask_ticks + deficit // 2 <= mid_ticks + k_ticks:
            ask_ticks += deficit // 2
            bid_ticks -= (deficit + 1) // 2
        else:
            # Can't satisfy both constraints - widen k_ticks
            bid_ticks = mid_ticks - (min_spread_ticks + 1) // 2
            ask_ticks = mid_ticks + min_spread_ticks // 2
    
    # Convert back to prices
    bid_price = from_ticks(bid_ticks, tick_dec)
    ask_price = from_ticks(ask_ticks, tick_dec)
    
    # Sanity check invariants
    assert bid_price <= mid_dec <= ask_price, f"Cross-mid violation: {bid_price} > {mid_dec} or {ask_price} < {mid_dec}"
    assert ask_price - bid_price >= tick_dec * min_spread_ticks, f"Spread too narrow: {ask_price - bid_price} < {tick_dec * min_spread_ticks}"
    
    return (bid_price, ask_price)


def is_multiple_of_tick(price: Price, tick_size: Price, tolerance: Decimal = Decimal('1e-10')) -> bool:
    """
    Check if price is an exact multiple of tick_size.
    
    Args:
        price: Price to check
        tick_size: Tick size
        tolerance: Tolerance for floating-point comparison
    
    Returns:
        True if price is multiple of tick_size
    
    Example:
        >>> is_multiple_of_tick(Decimal('50000.5'), Decimal('0.5'))
        True
        >>> is_multiple_of_tick(Decimal('50000.7'), Decimal('0.5'))
        False
    """
    price_dec = _to_decimal(price)
    tick_dec = _to_decimal(tick_size)
    _validate_tick_size(tick_dec)
    
    # Compute remainder
    ticks = price_dec / tick_dec
    remainder = abs(ticks - ticks.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    
    return remainder <= tolerance


# Per-symbol tick size management
_TICK_SIZE_CACHE: dict[str, Decimal] = {}


def register_tick_size(symbol: str, tick_size: Price) -> None:
    """
    Register tick size for a symbol.
    
    Args:
        symbol: Trading symbol (e.g., "BTCUSDT")
        tick_size: Tick size for symbol
    
    Raises:
        TickSizeError: If tick_size is invalid
    """
    tick_dec = _to_decimal(tick_size)
    _validate_tick_size(tick_dec)
    
    _TICK_SIZE_CACHE[symbol] = tick_dec


def get_tick_size(symbol: str, fallback: Price = Decimal('0.01')) -> Decimal:
    """
    Get tick size for symbol.
    
    Resolution order:
    1. Registered tick size (from register_tick_size)
    2. Fallback value
    
    Args:
        symbol: Trading symbol
        fallback: Fallback tick size if not registered
    
    Returns:
        Tick size as Decimal
    
    Raises:
        TickSizeError: If symbol not found and fallback is None
    """
    if symbol in _TICK_SIZE_CACHE:
        return _TICK_SIZE_CACHE[symbol]
    
    if fallback is None:
        raise TickSizeError(f"Tick size not registered for symbol: {symbol}")
    
    fallback_dec = _to_decimal(fallback)
    _validate_tick_size(fallback_dec)
    
    return fallback_dec


def clear_tick_size_cache() -> None:
    """Clear the tick size cache (for testing)."""
    _TICK_SIZE_CACHE.clear()


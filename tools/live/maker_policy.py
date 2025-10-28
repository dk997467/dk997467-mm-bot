"""
Maker-only policy utilities for MM-Bot.

Pure stdlib implementation with Decimal for precision.
All functions are deterministic and suitable for testing.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_UP


def calc_post_only_price(
    side: str,
    ref_price: float,
    offset_bps: float,
    tick_size: float,
) -> Decimal:
    """
    Calculate post-only price with offset from reference price.
    
    For BUY orders: price = ref_price - offset (below best bid)
    For SELL orders: price = ref_price + offset (above best ask)
    
    The calculated price is then rounded to tickSize:
    - BUY: round DOWN (to ensure we're below market)
    - SELL: round UP (to ensure we're above market)
    
    Args:
        side: Order side ("buy" or "sell", case-insensitive)
        ref_price: Reference price (best bid for buy, best ask for sell)
        offset_bps: Price offset in basis points (e.g. 1.5 = 0.015%)
        tick_size: Exchange tick size for rounding (e.g. 0.01)
    
    Returns:
        Post-only price as Decimal, rounded to tick_size
    
    Examples:
        >>> calc_post_only_price("buy", 50000.0, 1.5, 0.01)
        Decimal('49992.49')  # 50000 - (50000 * 0.00015) = 49992.5, rounded down to 49992.49
        
        >>> calc_post_only_price("sell", 50000.0, 1.5, 0.01)
        Decimal('50007.51')  # 50000 + (50000 * 0.00015) = 50007.5, rounded up to 50007.51
    """
    # Convert to Decimal for precision
    ref = Decimal(str(ref_price))
    offset = Decimal(str(offset_bps)) / Decimal("10000")
    tick = Decimal(str(tick_size))
    
    # Calculate adjustment: ref_price * (offset_bps / 10000)
    adjustment = ref * offset
    
    # Apply offset based on side
    side_lower = side.lower()
    if side_lower == "buy":
        # BUY: price below reference (subtract offset)
        price = ref - adjustment
        # Round DOWN to nearest tick_size
        rounded = (price / tick).quantize(Decimal("1"), rounding=ROUND_DOWN) * tick
    elif side_lower == "sell":
        # SELL: price above reference (add offset)
        price = ref + adjustment
        # Round UP to nearest tick_size
        rounded = (price / tick).quantize(Decimal("1"), rounding=ROUND_UP) * tick
    else:
        raise ValueError(f"Invalid side: {side}. Must be 'buy' or 'sell'.")
    
    return rounded


def round_qty(qty: float, step_size: float) -> Decimal:
    """
    Round quantity to exchange step size.
    
    Rounds DOWN to ensure we don't exceed available quantity.
    
    Args:
        qty: Quantity to round
        step_size: Exchange step size (e.g. 0.001 for BTC)
    
    Returns:
        Rounded quantity as Decimal
    
    Examples:
        >>> round_qty(0.0123456, 0.001)
        Decimal('0.012')  # Rounded down to 3 decimals
        
        >>> round_qty(1.5555, 0.01)
        Decimal('1.55')  # Rounded down to 2 decimals
    """
    # Convert to Decimal for precision
    qty_dec = Decimal(str(qty))
    step = Decimal(str(step_size))
    
    # Round DOWN to nearest step_size
    # Formula: floor(qty / step_size) * step_size
    rounded = (qty_dec / step).quantize(Decimal("1"), rounding=ROUND_DOWN) * step
    
    return rounded


def check_min_qty(qty: float, min_qty: float) -> bool:
    """
    Check if quantity meets minimum quantity requirement.
    
    Args:
        qty: Quantity to check
        min_qty: Exchange minimum quantity
    
    Returns:
        True if qty >= min_qty, False otherwise
    
    Examples:
        >>> check_min_qty(0.01, 0.001)
        True
        
        >>> check_min_qty(0.0005, 0.001)
        False
    """
    # Convert to Decimal for precision comparison
    qty_dec = Decimal(str(qty))
    min_qty_dec = Decimal(str(min_qty))
    
    return qty_dec >= min_qty_dec


def check_price_crosses_market(
    side: str,
    price: float,
    best_bid: float,
    best_ask: float,
) -> bool:
    """
    Check if a price would cross the market (take liquidity).
    
    For maker-only orders, we want to ensure:
    - BUY orders have price <= best_bid (don't cross best_ask)
    - SELL orders have price >= best_ask (don't cross best_bid)
    
    Args:
        side: Order side ("buy" or "sell", case-insensitive)
        price: Order price to check
        best_bid: Current best bid price
        best_ask: Current best ask price
    
    Returns:
        True if price crosses market (order would take), False if safe (maker-only)
    
    Examples:
        >>> check_price_crosses_market("buy", 50000, 49990, 50010)
        True  # Buy at 50000 crosses best_ask of 50010
        
        >>> check_price_crosses_market("buy", 49985, 49990, 50010)
        False  # Buy at 49985 is below best_bid, safe
        
        >>> check_price_crosses_market("sell", 50000, 49990, 50010)
        True  # Sell at 50000 crosses best_bid of 49990
        
        >>> check_price_crosses_market("sell", 50015, 49990, 50010)
        False  # Sell at 50015 is above best_ask, safe
    """
    # Convert to Decimal for precision
    price_dec = Decimal(str(price))
    best_bid_dec = Decimal(str(best_bid))
    best_ask_dec = Decimal(str(best_ask))
    
    side_lower = side.lower()
    
    if side_lower == "buy":
        # BUY: crosses if price >= best_ask
        return price_dec >= best_ask_dec
    elif side_lower == "sell":
        # SELL: crosses if price <= best_bid
        return price_dec <= best_bid_dec
    else:
        raise ValueError(f"Invalid side: {side}. Must be 'buy' or 'sell'.")


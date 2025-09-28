"""
Utility functions for the market maker bot.
"""

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import numpy as np
import orjson

try:
	from numba import njit
	numba_available = True
except Exception:
	numba_available = False


def json_dumps(obj: Any) -> str:
	"""Serialize object to JSON string using orjson."""
	# orjson.dumps returns bytes; decode to str
	return orjson.dumps(obj, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS).decode("utf-8")


def json_loads(s: str) -> Any:
	"""Deserialize JSON string to Python object using orjson."""
	if isinstance(s, (bytes, bytearray)):
		return orjson.loads(s)
	return orjson.loads(s.encode("utf-8"))


def j(obj: Any) -> str:
	"""Short helper for JSON serialization to string using orjson."""
	return orjson.dumps(obj, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS).decode("utf-8")


# --------- JIT-accelerated numeric helpers (numpy/numba) ---------

if numba_available:
	@njit(cache=True, fastmath=True)
	def _stddev_jit(x: np.ndarray) -> float:
		# Compute standard deviation of 1D array
		n = x.size
		if n <= 1:
			return 0.0
		m = 0.0
		m2 = 0.0
		for i in range(n):
			v = x[i]
			delta = v - m
			m += delta / (i + 1)
			m2 += delta * (v - m)
		return np.sqrt(m2 / n)
else:
	def _stddev_jit(x: np.ndarray) -> float:
		return float(np.std(x))


def round_to_tick_size(price: Decimal, tick_size: Decimal) -> Decimal:
    """Round price to the nearest valid tick size."""
    if tick_size <= 0:
        return price
    
    # Convert to float for numpy rounding, then back to Decimal
    price_float = float(price)
    tick_float = float(tick_size)
    
    rounded = np.round(price_float / tick_float) * tick_float
    return Decimal(str(rounded))


def round_to_lot_size(quantity: Decimal, lot_size: Decimal) -> Decimal:
    """Round quantity to the nearest valid lot size."""
    if lot_size <= 0:
        return quantity
    
    # Convert to float for numpy rounding, then back to Decimal
    qty_float = float(quantity)
    lot_float = float(lot_size)
    
    rounded = np.floor(qty_float / lot_float) * lot_float
    return Decimal(str(rounded))


def validate_quantity(
    quantity: Decimal, 
    lot_size: Decimal, 
    min_order_qty: Decimal,
    max_order_qty: Optional[Decimal] = None
) -> Tuple[bool, Optional[str]]:
    """Validate order quantity against exchange constraints."""
    if quantity <= 0:
        return False, "Quantity must be positive"
    
    if quantity < min_order_qty:
        return False, f"Quantity {quantity} below minimum {min_order_qty}"
    
    if max_order_qty and quantity > max_order_qty:
        return False, f"Quantity {quantity} above maximum {max_order_qty}"
    
    # Check if quantity is a multiple of lot size
    remainder = quantity % lot_size
    if remainder != 0:
        return False, f"Quantity {quantity} not a multiple of lot size {lot_size}"
    
    return True, None


def validate_price(
    price: Decimal, 
    tick_size: Decimal,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None
) -> Tuple[bool, Optional[str]]:
    """Validate order price against exchange constraints."""
    if price <= 0:
        return False, "Price must be positive"
    
    if min_price and price < min_price:
        return False, f"Price {price} below minimum {min_price}"
    
    if max_price and price > max_price:
        return False, f"Price {price} above maximum {max_price}"
    
    # Check if price is a multiple of tick size
    remainder = price % tick_size
    if remainder != 0:
        return False, f"Price {price} not a multiple of tick size {tick_size}"
    
    return True, None


def calculate_spread_bps(bid_price: Decimal, ask_price: Decimal) -> Decimal:
    """Calculate spread in basis points."""
    if bid_price <= 0 or ask_price <= 0:
        return Decimal(0)
    
    mid_price = (bid_price + ask_price) / 2
    spread = ask_price - bid_price
    return (spread / mid_price) * 10000


def calculate_microprice(
    bid_price: Decimal, 
    ask_price: Decimal, 
    bid_size: Decimal, 
    ask_size: Decimal
) -> Decimal:
    """Calculate microprice based on order book imbalance."""
    if bid_size <= 0 or ask_size <= 0:
        return (bid_price + ask_price) / 2
    
    total_size = bid_size + ask_size
    bid_weight = ask_size / total_size
    ask_weight = bid_size / total_size
    
    return bid_price * bid_weight + ask_price * ask_weight


def calculate_volatility(
    prices: List[Decimal], 
    lookback_periods: int = 30
) -> Decimal:
    """Calculate volatility using standard deviation of returns."""
    if len(prices) < 2:
        return Decimal(0)
    
    # Convert tail to numpy float array
    limit = min(len(prices), lookback_periods + 1)
    arr = np.array([float(p) for p in prices[:limit]], dtype=np.float64)
    if arr.size < 2:
        return Decimal(0)
    returns = np.diff(arr) / arr[:-1]
    if returns.size == 0:
        return Decimal(0)
    vol = _stddev_jit(returns)
    return Decimal(str(vol))


def calculate_imbalance(bids: List[Decimal], asks: List[Decimal]) -> Decimal:
    """Calculate order book imbalance."""
    if not bids or not asks:
        return Decimal(0)
    bid_arr = np.array([float(x) for x in bids], dtype=np.float64)
    ask_arr = np.array([float(x) for x in asks], dtype=np.float64)
    total = bid_arr.sum() + ask_arr.sum()
    if total == 0.0:
        return Decimal(0)
    return Decimal(str((bid_arr.sum() - ask_arr.sum()) / total))


def generate_signature(
    api_secret: str, 
    timestamp: int, 
    recv_window: int, 
    params: Dict[str, Any]
) -> str:
    """Generate HMAC signature for Bybit API authentication."""
    # Sort parameters by key
    sorted_params = dict(sorted(params.items()))
    
    # Add timestamp and recv_window
    sorted_params['timestamp'] = timestamp
    sorted_params['recvWindow'] = recv_window
    
    # Create query string
    query_string = urlencode(sorted_params)
    
    # Generate signature
    signature = hmac.new(
        api_secret.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return signature


def generate_idempotency_key() -> str:
    """Generate a unique idempotency key."""
    timestamp = int(time.time() * 1000000)  # Microseconds
    random_part = np.random.randint(1000, 9999)
    return f"{timestamp}_{random_part}"


def exponential_backoff_delay(
    attempt: int, 
    base_delay: float = 1.0, 
    max_delay: float = 60.0,
    jitter: bool = True
) -> float:
    """Calculate exponential backoff delay with optional jitter."""
    delay = min(base_delay * (2 ** attempt), max_delay)
    
    if jitter:
        # Add random jitter (±25%)
        jitter_factor = 0.75 + 0.5 * np.random.random()
        delay *= jitter_factor
    
    return delay


def timestamp_to_datetime(timestamp: int) -> datetime:
    """Convert timestamp to datetime."""
    if timestamp > 1e10:  # Assume milliseconds
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def datetime_to_timestamp(dt: datetime) -> int:
    """Convert datetime to timestamp in milliseconds."""
    return int(dt.timestamp() * 1000)


def format_decimal(value: Decimal, precision: int = 8) -> str:
    """Format decimal with specified precision."""
    return f"{value:.{precision}f}"


def parse_decimal(value: Any) -> Decimal:
    """Parse value to Decimal, handling various input types."""
    if isinstance(value, Decimal):
        return value
    elif isinstance(value, (int, float)):
        return Decimal(str(value))
    elif isinstance(value, str):
        return Decimal(value)
    else:
        raise ValueError(f"Cannot convert {type(value)} to Decimal")


def safe_divide(numerator: Decimal, denominator: Decimal, default: Decimal = Decimal(0)) -> Decimal:
    """Safely divide two decimals, returning default if denominator is zero."""
    if denominator == 0:
        return default
    return numerator / denominator


def clamp(value: Decimal, min_val: Decimal, max_val: Decimal) -> Decimal:
    """Clamp value between min and max."""
    return max(min_val, min(value, max_val))


async def retry_with_backoff(
    func, 
    max_attempts: int = 3, 
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,)
):
    """Retry function with exponential backoff."""
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            if attempt < max_attempts - 1:
                delay = exponential_backoff_delay(attempt, base_delay, max_delay)
                await asyncio.sleep(delay)
    
    raise last_exception


def calculate_pnl(
    entry_price: Decimal, 
    exit_price: Decimal, 
    quantity: Decimal, 
    side: str
) -> Decimal:
    """Calculate P&L for a trade."""
    if side.upper() == "BUY":
        return (exit_price - entry_price) * quantity
    else:  # SELL
        return (entry_price - exit_price) * quantity


def calculate_fees(
    notional: Decimal, 
    fee_rate: Decimal, 
    is_maker: bool = True
) -> Decimal:
    """Calculate trading fees."""
    # Maker fees are typically lower than taker fees
    effective_rate = fee_rate * (0.8 if is_maker else 1.0)
    return notional * effective_rate


def is_market_open() -> bool:
    """Check if market is currently open (simplified - always returns True for crypto)."""
    return True  # Crypto markets are 24/7


def log_structured(
    level: str, 
    message: str, 
    **kwargs
) -> Dict[str, Any]:
    """Create structured log entry."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "message": message,
        **kwargs
    }


def round_floats(obj: Any, dp: int = 2) -> Any:
    """Recursively round floating point numbers in nested data structures."""
    if isinstance(obj, float):
        return round(obj, dp)
    elif isinstance(obj, dict):
        return {k: round_floats(v, dp) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return type(obj)(round_floats(item, dp) for item in obj)
    else:
        return obj
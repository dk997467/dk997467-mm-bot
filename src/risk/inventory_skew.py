"""
Inventory-skew calculator for automatic inventory management.

Adjusts bid/ask spreads based on current inventory position to encourage
rebalancing and reduce adverse selection risk.
"""
from src.common.config import InventorySkewConfig
from typing import Dict, Any


def compute_skew_bps(cfg: InventorySkewConfig, inventory_pct: float) -> float:
    """
    Compute inventory skew in basis points.
    
    Positive skew = long inventory → push asks down (sell faster), bids up less (buy slower)
    Negative skew = short inventory → push bids up (buy faster), asks down less (sell slower)
    
    Args:
        cfg: Inventory skew configuration
        inventory_pct: Current inventory as % of max position
                       Positive = long, negative = short
    
    Returns:
        Skew in basis points (can be positive or negative)
    """
    if not cfg.enabled:
        return 0.0
    
    # Calculate deviation from target
    delta_pct = inventory_pct - cfg.target_pct
    
    # Apply clamp (noise filter)
    if abs(delta_pct) < cfg.clamp_pct:
        return 0.0
    
    # Calculate raw skew
    raw_skew = delta_pct * cfg.slope_bps_per_1pct
    
    # Apply max limit
    skew_bps = max(-cfg.max_skew_bps, min(cfg.max_skew_bps, raw_skew))
    
    return skew_bps


def apply_inventory_skew(cfg: InventorySkewConfig, 
                        inventory_pct: float,
                        bid_price: float,
                        ask_price: float) -> Dict[str, float]:
    """
    Apply inventory skew to bid/ask prices.
    
    For long inventory (positive skew):
    - Push ask down (more aggressive selling)
    - Keep bid unchanged or slightly lower (less aggressive buying)
    
    For short inventory (negative skew):
    - Push bid up (more aggressive buying)
    - Keep ask unchanged or slightly higher (less aggressive selling)
    
    Args:
        cfg: Inventory skew configuration
        inventory_pct: Current inventory as % of max position
        bid_price: Original bid price
        ask_price: Original ask price
    
    Returns:
        dict with keys:
            - bid_price: Adjusted bid price
            - ask_price: Adjusted ask price
            - skew_bps: Applied skew in bps
            - bid_adj_bps: Bid adjustment in bps
            - ask_adj_bps: Ask adjustment in bps
    """
    skew_bps = compute_skew_bps(cfg, inventory_pct)
    
    if skew_bps == 0.0:
        return {
            'bid_price': bid_price,
            'ask_price': ask_price,
            'skew_bps': 0.0,
            'bid_adj_bps': 0.0,
            'ask_adj_bps': 0.0,
        }
    
    # Calculate mid for reference
    mid_price = (bid_price + ask_price) / 2.0
    
    # For positive skew (long inventory):
    # - Reduce ask (sell faster): ask -= skew_bps/2
    # - Keep bid or reduce slightly: bid -= skew_bps/4
    #
    # For negative skew (short inventory):
    # - Increase bid (buy faster): bid += abs(skew_bps)/2
    # - Keep ask or increase slightly: ask += abs(skew_bps)/4
    
    if skew_bps > 0:
        # Long inventory - push to sell
        ask_adj_bps = -skew_bps / 2.0  # Negative = more aggressive
        bid_adj_bps = -skew_bps / 4.0  # Slightly less aggressive on buy side
    else:
        # Short inventory - push to buy
        bid_adj_bps = -skew_bps / 2.0  # Positive = more aggressive (skew is negative)
        ask_adj_bps = -skew_bps / 4.0  # Slightly less aggressive on sell side
    
    # Apply adjustments
    adj_bid = bid_price * (1 + bid_adj_bps / 10000.0)
    adj_ask = ask_price * (1 + ask_adj_bps / 10000.0)
    
    # Sanity check: bid should still be < ask
    if adj_bid >= adj_ask:
        # Revert to original prices if we'd cross spread
        adj_bid = bid_price
        adj_ask = ask_price
        bid_adj_bps = 0.0
        ask_adj_bps = 0.0
    
    return {
        'bid_price': adj_bid,
        'ask_price': adj_ask,
        'skew_bps': skew_bps,
        'bid_adj_bps': bid_adj_bps,
        'ask_adj_bps': ask_adj_bps,
    }


def get_inventory_pct(position_base: float, max_position_base: float) -> float:
    """
    Calculate inventory as percentage of max position.
    
    Args:
        position_base: Current position in base currency (can be negative)
        max_position_base: Maximum allowed position (absolute value)
    
    Returns:
        Inventory percentage (-100 to +100)
        Positive = long, negative = short
    """
    if max_position_base <= 0:
        return 0.0
    
    inventory_pct = (position_base / max_position_base) * 100.0
    
    # Clamp to [-100, 100]
    return max(-100.0, min(100.0, inventory_pct))


def compute_target_spread_shift(cfg: InventorySkewConfig,
                                inventory_pct: float,
                                base_spread_bps: float) -> Dict[str, float]:
    """
    Compute target spread shift based on inventory.
    
    This is an alternative approach that shifts the entire spread
    rather than individual bid/ask prices.
    
    Args:
        cfg: Inventory skew configuration
        inventory_pct: Current inventory as % of max position
        base_spread_bps: Base spread in basis points
    
    Returns:
        dict with:
            - spread_shift_bps: How much to shift spread center
            - bid_shift_bps: Bid adjustment
            - ask_shift_bps: Ask adjustment
    """
    skew_bps = compute_skew_bps(cfg, inventory_pct)
    
    if skew_bps == 0.0:
        return {
            'spread_shift_bps': 0.0,
            'bid_shift_bps': 0.0,
            'ask_shift_bps': 0.0,
        }
    
    # For long inventory (positive skew):
    # Shift spread center down (both bid and ask go down)
    # This makes us more competitive on the sell side
    #
    # For short inventory (negative skew):
    # Shift spread center up (both bid and ask go up)
    # This makes us more competitive on the buy side
    
    spread_shift_bps = -skew_bps / 2.0  # Negative for long, positive for short
    
    return {
        'spread_shift_bps': spread_shift_bps,
        'bid_shift_bps': spread_shift_bps,
        'ask_shift_bps': spread_shift_bps,
    }

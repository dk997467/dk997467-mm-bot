"""
Queue-aware quoting for optimal queue positioning.

Estimates queue position based on order book depth and dynamically
micro-adjusts prices to improve fill probability without crossing spread.
"""
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from src.common.config import QueueAwareConfig


@dataclass
class Quote:
    """Simple quote representation."""
    symbol: str
    side: str  # 'bid' or 'ask'
    price: float
    size: float


def estimate_queue_position(book: Dict[str, Any], side: str, price: float, 
                           size: float, depth_levels: int = 3) -> Dict[str, Any]:
    """
    Estimate queue position for an order at given price.
    
    Args:
        book: Order book dict with 'bids' and 'asks' lists
        side: 'bid' or 'ask'
        price: Order price
        size: Order size
        depth_levels: Number of book levels to analyze
    
    Returns:
        dict with:
            - ahead_qty: Quantity ahead of us in queue
            - percentile: Queue position as percentile (0=best, 100=worst)
            - level: Price level (0=best, 1=second, etc.)
            - at_best: Whether we're at best price
    """
    side_key = 'bids' if side == 'bid' else 'asks'
    levels = book.get(side_key, [])
    
    if not levels:
        return {
            'ahead_qty': 0.0,
            'percentile': 0.0,
            'level': 0,
            'at_best': True,
            'total_qty': 0.0,
        }
    
    # Limit analysis to depth_levels
    levels = levels[:depth_levels]
    
    # Find our price level
    our_level = -1
    ahead_qty = 0.0
    total_qty = 0.0
    at_best = False
    
    for i, level in enumerate(levels):
        level_price = float(level[0])
        level_qty = float(level[1])
        total_qty += level_qty
        
        if side == 'bid':
            if level_price > price:
                # Better price, all this qty is ahead
                ahead_qty += level_qty
            elif level_price == price:
                # Same price, we join queue (assume we're at back)
                ahead_qty += level_qty
                our_level = i
                at_best = (i == 0)
                break
        else:  # ask
            if level_price < price:
                # Better price, all this qty is ahead
                ahead_qty += level_qty
            elif level_price == price:
                # Same price, we join queue
                ahead_qty += level_qty
                our_level = i
                at_best = (i == 0)
                break
    
    # If price not found in book, we're either improving or beyond depth
    if our_level == -1:
        best_price = float(levels[0][0])
        
        if side == 'bid':
            if price > best_price:
                # Improving best bid
                ahead_qty = 0.0
                our_level = -1  # Better than level 0
                at_best = True
            else:
                # Worse than visible depth
                ahead_qty = total_qty
                our_level = len(levels)
                at_best = False
        else:  # ask
            if price < best_price:
                # Improving best ask
                ahead_qty = 0.0
                our_level = -1
                at_best = True
            else:
                # Worse than visible depth
                ahead_qty = total_qty
                our_level = len(levels)
                at_best = False
    
    # Calculate percentile (0=best, 100=worst)
    if total_qty > 0:
        percentile = (ahead_qty / total_qty) * 100.0
    else:
        percentile = 0.0
    
    # Clamp to [0, 100]
    percentile = max(0.0, min(100.0, percentile))
    
    return {
        'ahead_qty': ahead_qty,
        'percentile': percentile,
        'level': max(0, our_level),
        'at_best': at_best,
        'total_qty': total_qty,
    }


class QueueAwareRepricer:
    """
    Queue-aware repricing engine.
    
    Monitors queue position and suggests micro-adjustments to improve
    fill probability while respecting rate limits and fair value constraints.
    """
    
    def __init__(self, cfg: QueueAwareConfig):
        """
        Initialize repricer.
        
        Args:
            cfg: Queue-aware configuration
        """
        self.cfg = cfg
        self.last_nudge_ms: Dict[str, int] = {}  # symbol -> last nudge timestamp
    
    def maybe_nudge(self, quote: Quote, book: Dict[str, Any], 
                   now_ms: int, fair_value: float = None,
                   in_cooldown: bool = False) -> Optional[Quote]:
        """
        Check if quote should be nudged to improve queue position.
        
        Args:
            quote: Current quote
            book: Order book snapshot
            now_ms: Current timestamp in milliseconds
            fair_value: Optional fair value constraint (don't cross this)
            in_cooldown: If True, skip nudging (fast-cancel cooldown active)
        
        Returns:
            New Quote if nudge recommended, None otherwise
        """
        if not self.cfg.enabled:
            return None
        
        if in_cooldown:
            # Respect fast-cancel cooldown
            return None
        
        # Check headroom (rate limit)
        symbol = quote.symbol
        last_nudge = self.last_nudge_ms.get(symbol, 0)
        if (now_ms - last_nudge) < self.cfg.headroom_ms:
            # Too soon since last nudge
            return None
        
        # Estimate queue position
        queue_pos = estimate_queue_position(
            book, quote.side, quote.price, quote.size,
            depth_levels=self.cfg.book_depth_levels
        )
        
        # Check if we need to nudge
        if queue_pos['percentile'] <= self.cfg.join_threshold_pct:
            # Good position, no need to nudge
            return None
        
        if queue_pos['at_best']:
            # Already at best, can't improve
            return None
        
        # Calculate nudge direction and amount
        if quote.side == 'bid':
            # For bids, nudge up (more aggressive)
            nudge_direction = 1
            best_price = float(book.get('bids', [[0]])[0][0]) if book.get('bids') else quote.price
        else:
            # For asks, nudge down (more aggressive)
            nudge_direction = -1
            best_price = float(book.get('asks', [[0]])[0][0]) if book.get('asks') else quote.price
        
        # Calculate max nudge in absolute price
        max_nudge_bps = self.cfg.max_reprice_bps
        max_nudge = (max_nudge_bps / 10000.0) * quote.price
        
        # Nudge towards best price, but not beyond
        if quote.side == 'bid':
            new_price = min(quote.price + max_nudge, best_price)
        else:
            new_price = max(quote.price - max_nudge, best_price)
        
        # Check fair value constraint
        if fair_value is not None:
            if quote.side == 'bid':
                # Don't bid above fair value
                if new_price > fair_value:
                    new_price = min(new_price, fair_value)
            else:
                # Don't ask below fair value
                if new_price < fair_value:
                    new_price = max(new_price, fair_value)
        
        # Check if nudge is meaningful
        price_delta = abs(new_price - quote.price)
        if price_delta < (0.01 / 10000.0) * quote.price:  # < 0.01 bps
            return None
        
        # Record nudge time
        self.last_nudge_ms[symbol] = now_ms
        
        # Return nudged quote
        return Quote(
            symbol=quote.symbol,
            side=quote.side,
            price=new_price,
            size=quote.size
        )
    
    def get_nudge_stats(self) -> Dict[str, Any]:
        """Get statistics about nudging activity."""
        return {
            'symbols_nudged': len(self.last_nudge_ms),
            'last_nudge_times': dict(self.last_nudge_ms),
        }
    
    def reset(self) -> None:
        """Reset nudge tracking."""
        self.last_nudge_ms.clear()

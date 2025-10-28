"""
Position Tracker — Real-time position and P&L tracking.

Features:
- Multi-symbol position tracking
- Real-time P&L calculation (realized + unrealized)
- Fill event processing
- Position reconciliation
- Persistence hooks (for Redis/file storage)

Position Calculation:
- Long position: positive qty (accumulated buys - sells)
- Short position: negative qty
- Realized P&L: locked profit/loss from closed positions
- Unrealized P&L: mark-to-market on open positions
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Literal
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tools.live.exchange_client import FillEvent

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Position record for a single symbol."""
    
    symbol: str
    qty: float = 0.0  # Net position (positive=long, negative=short)
    avg_entry_price: float = 0.0  # Volume-weighted average entry price
    realized_pnl: float = 0.0  # Cumulative realized P&L
    unrealized_pnl: float = 0.0  # Mark-to-market P&L (updated on mark price change)
    total_buy_qty: float = 0.0  # Cumulative buy quantity (for stats)
    total_sell_qty: float = 0.0  # Cumulative sell quantity (for stats)
    total_buy_notional: float = 0.0  # Cumulative buy notional (qty * price)
    total_sell_notional: float = 0.0  # Cumulative sell notional (qty * price)
    last_mark_price: Optional[float] = None  # Last mark price (for unrealized P&L)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict:
        """Convert to dict for serialization."""
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "avg_entry_price": self.avg_entry_price,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_buy_qty": self.total_buy_qty,
            "total_sell_qty": self.total_sell_qty,
            "total_buy_notional": self.total_buy_notional,
            "total_sell_notional": self.total_sell_notional,
            "last_mark_price": self.last_mark_price,
            "updated_at": self.updated_at,
        }


class PositionTracker:
    """
    Position tracker for multi-symbol trading.
    
    Responsibilities:
    - Track net position per symbol
    - Calculate average entry price (VWAP)
    - Calculate realized P&L on position closes
    - Calculate unrealized P&L on mark price updates
    - Persist positions to storage (Redis/file)
    
    Usage:
        tracker = PositionTracker()
        
        # Apply fill
        fill = FillEvent(...)
        tracker.apply_fill(fill)
        
        # Update mark price
        tracker.update_mark_price("BTCUSDT", 50000.0)
        
        # Get position
        pos = tracker.get_position("BTCUSDT")
        print(f"Position: {pos.qty}, P&L: {pos.realized_pnl + pos.unrealized_pnl}")
    """
    
    def __init__(self):
        """Initialize position tracker."""
        self._positions: Dict[str, Position] = {}
        logger.info("PositionTracker initialized")
    
    def apply_fill(self, fill: FillEvent) -> Position:
        """
        Apply fill event to update position.
        
        Args:
            fill: FillEvent from exchange
        
        Returns:
            Updated Position
        
        Logic:
        - Buy: Increase position qty, update avg entry price
        - Sell: Decrease position qty, realize P&L if closing
        """
        symbol = fill.symbol
        fill_qty = fill.fill_qty
        fill_price = fill.fill_price
        side = fill.side
        
        # Get or create position
        pos = self._positions.get(symbol)
        if not pos:
            pos = Position(symbol=symbol)
            self._positions[symbol] = pos
        
        # Store old position for P&L calculation
        old_qty = pos.qty
        old_avg_price = pos.avg_entry_price
        
        # Apply fill based on side
        if side == "Buy":
            self._apply_buy(pos, fill_qty, fill_price, old_qty, old_avg_price)
        elif side == "Sell":
            self._apply_sell(pos, fill_qty, fill_price, old_qty, old_avg_price)
        else:
            raise ValueError(f"Invalid side: {side}")
        
        # Update timestamp
        pos.updated_at = datetime.now(timezone.utc).isoformat()
        
        logger.info(
            f"Fill applied: {symbol} {side} {fill_qty}@{fill_price} "
            f"→ pos={pos.qty:.6f}, rpnl={pos.realized_pnl:.2f}, "
            f"upnl={pos.unrealized_pnl:.2f}"
        )
        
        return pos
    
    def _apply_buy(
        self,
        pos: Position,
        fill_qty: float,
        fill_price: float,
        old_qty: float,
        old_avg_price: float,
    ) -> None:
        """Apply buy fill to position."""
        # Update stats
        pos.total_buy_qty += fill_qty
        pos.total_buy_notional += fill_qty * fill_price
        
        # Calculate new position
        new_qty = old_qty + fill_qty
        
        if old_qty >= 0:
            # Increasing long or opening long
            # Update avg entry price (VWAP)
            if new_qty > 0:
                pos.avg_entry_price = (
                    (old_qty * old_avg_price + fill_qty * fill_price) / new_qty
                )
            pos.qty = new_qty
        
        elif old_qty < 0:
            # Closing short or flipping to long
            if abs(old_qty) >= fill_qty:
                # Closing short (partial or full)
                close_qty = fill_qty
                realized_pnl = close_qty * (old_avg_price - fill_price)  # Short P&L
                pos.realized_pnl += realized_pnl
                pos.qty = old_qty + fill_qty
                
                # If fully closed, reset avg price
                if abs(pos.qty) < 1e-8:
                    pos.qty = 0.0
                    pos.avg_entry_price = 0.0
            
            else:
                # Flipping from short to long
                close_qty = abs(old_qty)
                open_qty = fill_qty - close_qty
                
                # Realize P&L on closed short
                realized_pnl = close_qty * (old_avg_price - fill_price)
                pos.realized_pnl += realized_pnl
                
                # Open new long position
                pos.qty = open_qty
                pos.avg_entry_price = fill_price
    
    def _apply_sell(
        self,
        pos: Position,
        fill_qty: float,
        fill_price: float,
        old_qty: float,
        old_avg_price: float,
    ) -> None:
        """Apply sell fill to position."""
        # Update stats
        pos.total_sell_qty += fill_qty
        pos.total_sell_notional += fill_qty * fill_price
        
        # Calculate new position
        new_qty = old_qty - fill_qty
        
        if old_qty <= 0:
            # Increasing short or opening short
            # Update avg entry price (VWAP)
            if new_qty < 0:
                pos.avg_entry_price = (
                    (abs(old_qty) * old_avg_price + fill_qty * fill_price) / abs(new_qty)
                )
            pos.qty = new_qty
        
        elif old_qty > 0:
            # Closing long or flipping to short
            if old_qty >= fill_qty:
                # Closing long (partial or full)
                close_qty = fill_qty
                realized_pnl = close_qty * (fill_price - old_avg_price)  # Long P&L
                pos.realized_pnl += realized_pnl
                pos.qty = old_qty - fill_qty
                
                # If fully closed, reset avg price
                if abs(pos.qty) < 1e-8:
                    pos.qty = 0.0
                    pos.avg_entry_price = 0.0
            
            else:
                # Flipping from long to short
                close_qty = old_qty
                open_qty = fill_qty - close_qty
                
                # Realize P&L on closed long
                realized_pnl = close_qty * (fill_price - old_avg_price)
                pos.realized_pnl += realized_pnl
                
                # Open new short position
                pos.qty = -open_qty
                pos.avg_entry_price = fill_price
    
    def update_mark_price(self, symbol: str, mark_price: float) -> Position:
        """
        Update mark price and recalculate unrealized P&L.
        
        Args:
            symbol: Trading symbol
            mark_price: Current mark price
        
        Returns:
            Updated Position
        """
        pos = self._positions.get(symbol)
        if not pos:
            # No position, create empty one
            pos = Position(symbol=symbol, last_mark_price=mark_price)
            self._positions[symbol] = pos
            return pos
        
        # Update unrealized P&L
        if pos.qty != 0 and pos.avg_entry_price > 0:
            if pos.qty > 0:
                # Long position
                pos.unrealized_pnl = pos.qty * (mark_price - pos.avg_entry_price)
            else:
                # Short position
                pos.unrealized_pnl = abs(pos.qty) * (pos.avg_entry_price - mark_price)
        else:
            pos.unrealized_pnl = 0.0
        
        pos.last_mark_price = mark_price
        pos.updated_at = datetime.now(timezone.utc).isoformat()
        
        return pos
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get position for symbol.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Position or None if not found
        """
        return self._positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Position]:
        """
        Get all positions.
        
        Returns:
            Dict mapping symbol to Position
        """
        return self._positions.copy()
    
    def get_total_pnl(self) -> float:
        """
        Get total P&L (realized + unrealized) across all positions.
        
        Returns:
            Total P&L
        """
        return sum(
            pos.realized_pnl + pos.unrealized_pnl
            for pos in self._positions.values()
        )
    
    def get_total_realized_pnl(self) -> float:
        """
        Get total realized P&L across all positions.
        
        Returns:
            Total realized P&L
        """
        return sum(pos.realized_pnl for pos in self._positions.values())
    
    def get_total_unrealized_pnl(self) -> float:
        """
        Get total unrealized P&L across all positions.
        
        Returns:
            Total unrealized P&L
        """
        return sum(pos.unrealized_pnl for pos in self._positions.values())
    
    def reconcile_position(
        self,
        symbol: str,
        exchange_qty: float,
        exchange_avg_price: float,
    ) -> bool:
        """
        Reconcile position with exchange (detect drift).
        
        Args:
            symbol: Trading symbol
            exchange_qty: Position qty reported by exchange
            exchange_avg_price: Avg entry price reported by exchange
        
        Returns:
            True if positions match, False if drift detected
        """
        pos = self._positions.get(symbol)
        if not pos:
            # No local position, check if exchange has one
            if abs(exchange_qty) < 1e-8:
                logger.info(f"Reconciliation OK: {symbol} (no position)")
                return True
            else:
                logger.error(
                    f"Position drift: {symbol} local=0, exchange={exchange_qty}"
                )
                return False
        
        # Compare quantities (allow small float error)
        qty_diff = abs(pos.qty - exchange_qty)
        price_diff = abs(pos.avg_entry_price - exchange_avg_price)
        
        if qty_diff < 1e-6 and price_diff < 0.01:
            logger.info(
                f"Reconciliation OK: {symbol} qty={pos.qty:.6f}, "
                f"avg_price={pos.avg_entry_price:.2f}"
            )
            return True
        else:
            logger.error(
                f"Position drift detected: {symbol} "
                f"local_qty={pos.qty:.6f}, exchange_qty={exchange_qty:.6f}, "
                f"local_price={pos.avg_entry_price:.2f}, exchange_price={exchange_avg_price:.2f}"
            )
            return False
    
    def persist_to_dict(self) -> Dict:
        """
        Serialize all positions to dict (for persistence).
        
        Returns:
            Dict representation of all positions
        """
        return {
            "positions": {
                symbol: pos.to_dict()
                for symbol, pos in self._positions.items()
            },
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
            "total_pnl": self.get_total_pnl(),
            "total_realized_pnl": self.get_total_realized_pnl(),
            "total_unrealized_pnl": self.get_total_unrealized_pnl(),
        }
    
    def restore_from_dict(self, data: Dict) -> None:
        """
        Restore positions from dict (after restart).
        
        Args:
            data: Dict from persist_to_dict()
        """
        positions_data = data.get("positions", {})
        
        for symbol, pos_dict in positions_data.items():
            pos = Position(
                symbol=pos_dict["symbol"],
                qty=pos_dict.get("qty", 0.0),
                avg_entry_price=pos_dict.get("avg_entry_price", 0.0),
                realized_pnl=pos_dict.get("realized_pnl", 0.0),
                unrealized_pnl=pos_dict.get("unrealized_pnl", 0.0),
                total_buy_qty=pos_dict.get("total_buy_qty", 0.0),
                total_sell_qty=pos_dict.get("total_sell_qty", 0.0),
                total_buy_notional=pos_dict.get("total_buy_notional", 0.0),
                total_sell_notional=pos_dict.get("total_sell_notional", 0.0),
                last_mark_price=pos_dict.get("last_mark_price"),
                updated_at=pos_dict.get("updated_at", datetime.now(timezone.utc).isoformat()),
            )
            self._positions[symbol] = pos
        
        logger.info(f"Restored {len(self._positions)} positions from persistence")


# Convenience function
def create_tracker() -> PositionTracker:
    """
    Factory function to create PositionTracker.
    
    Returns:
        PositionTracker instance
    """
    return PositionTracker()


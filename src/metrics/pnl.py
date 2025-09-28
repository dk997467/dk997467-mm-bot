"""
PnL attribution and calculation module.

Provides helpers for:
- Maker rebate calculation
- Taker fees calculation  
- Realized PnL tracking
- Unrealized PnL estimation
- Inventory tracking
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.common.config import AppConfig
from src.common.models import Order, Side

logger = logging.getLogger(__name__)


@dataclass
class PnLBreakdown:
    """Breakdown of PnL components."""
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    maker_rebate: float = 0.0
    taker_fees: float = 0.0
    total_pnl: float = 0.0
    
    def __post_init__(self):
        """Calculate total PnL."""
        self.total_pnl = self.realized_pnl + self.unrealized_pnl


class PnLAttributor:
    """PnL attribution and calculation engine."""
    
    def __init__(self, ctx: AppConfig):
        """Initialize PnL attributor."""
        self.ctx = ctx
        
        # Fee rates from config
        self.maker_fee_bps = getattr(ctx.trading, 'maker_fee_bps', 1.0) / 10000
        self.taker_fee_bps = getattr(ctx.trading, 'taker_fee_bps', 5.0) / 10000
        
        # Inventory tracking per symbol
        self.inventory: Dict[str, float] = {}  # symbol -> base currency amount
        self.avg_prices: Dict[str, Dict[str, float]] = {}  # symbol -> {side -> avg_price}
        self.realized_pnl: Dict[str, float] = {}  # symbol -> realized PnL
        
        # Fill history for PnL calculation
        self.fills: Dict[str, List[Dict]] = {}  # symbol -> list of fills
        
        logger.info(f"PnL attributor initialized: maker_fee={self.maker_fee_bps*10000:.2f}bps, taker_fee={self.taker_fee_bps*10000:.2f}bps")
    
    def calculate_maker_rebate(self, fill_qty: float, fill_price: float, symbol: str) -> float:
        """Calculate maker rebate for a fill."""
        notional = fill_qty * fill_price
        rebate = notional * self.maker_fee_bps
        
        logger.debug(f"Maker rebate: {fill_qty} @ {fill_price} = {rebate:.6f} {symbol}")
        return rebate
    
    def calculate_taker_fees(self, fill_qty: float, fill_price: float, symbol: str) -> float:
        """Calculate taker fees for a fill."""
        notional = fill_qty * fill_price
        fees = notional * self.taker_fee_bps
        
        logger.debug(f"Taker fees: {fill_qty} @ {fill_price} = {fees:.6f} {symbol}")
        return fees
    
    def record_fill(self, symbol: str, side: str, fill_qty: float, fill_price: float, 
                   is_maker: bool = True, order_id: str = None):
        """Record a fill and update inventory/PnL."""
        # Initialize if needed
        if symbol not in self.inventory:
            self.inventory[symbol] = 0.0
            self.avg_prices[symbol] = {'Buy': 0.0, 'Sell': 0.0}
            self.realized_pnl[symbol] = 0.0
            self.fills[symbol] = []
        
        # Record fill
        fill_record = {
            'timestamp': datetime.now(timezone.utc),
            'order_id': order_id,
            'side': side,
            'qty': fill_qty,
            'price': fill_price,
            'is_maker': is_maker,
            'notional': fill_qty * fill_price
        }
        self.fills[symbol].append(fill_record)
        
        # Calculate fees/rebate
        if is_maker:
            rebate = self.calculate_maker_rebate(fill_qty, fill_price, symbol)
            self.realized_pnl[symbol] += rebate
        else:
            fees = self.calculate_taker_fees(fill_qty, fill_price, symbol)
            self.realized_pnl[symbol] -= fees
        
        # Update inventory
        if side == 'Buy':
            self.inventory[symbol] += fill_qty
            # Update average price for buys
            if self.avg_prices[symbol]['Buy'] == 0:
                self.avg_prices[symbol]['Buy'] = fill_price
            else:
                # Weighted average
                total_qty = sum(f['qty'] for f in self.fills[symbol] if f['side'] == 'Buy')
                total_value = sum(f['qty'] * f['price'] for f in self.fills[symbol] if f['side'] == 'Buy')
                self.avg_prices[symbol]['Buy'] = total_value / total_qty
        else:  # Sell
            self.inventory[symbol] -= fill_qty
            # Update average price for sells
            if self.avg_prices[symbol]['Sell'] == 0:
                self.avg_prices[symbol]['Sell'] = fill_price
            else:
                # Weighted average
                total_qty = sum(f['qty'] for f in self.fills[symbol] if f['side'] == 'Sell')
                total_value = sum(f['qty'] * f['price'] for f in self.fills[symbol] if f['side'] == 'Sell')
                self.avg_prices[symbol]['Sell'] = total_value / total_qty
        
        logger.info(f"Fill recorded: {side} {fill_qty} @ {fill_price} {symbol}, inventory: {self.inventory[symbol]:.6f}")
    
    def calculate_realized_pnl(self, symbol: str) -> float:
        """Get realized PnL for symbol."""
        return self.realized_pnl.get(symbol, 0.0)
    
    def calculate_unrealized_pnl(self, symbol: str, current_price: float) -> float:
        """Calculate unrealized PnL based on current market price."""
        if symbol not in self.inventory or self.inventory[symbol] == 0:
            return 0.0
        
        # For long positions (positive inventory), unrealized PnL = (current - avg_buy) * qty
        # For short positions (negative inventory), unrealized PnL = (avg_sell - current) * qty
        
        inventory = self.inventory[symbol]
        if inventory > 0:  # Long position
            avg_buy = self.avg_prices[symbol]['Buy']
            if avg_buy > 0:
                unrealized = (current_price - avg_buy) * inventory
            else:
                unrealized = 0.0
        else:  # Short position
            avg_sell = self.avg_prices[symbol]['Sell']
            if avg_sell > 0:
                unrealized = (avg_sell - current_price) * abs(inventory)
            else:
                unrealized = 0.0
        
        return unrealized
    
    def get_total_pnl(self, symbol: str, current_price: float) -> PnLBreakdown:
        """Get total PnL breakdown for symbol."""
        realized = self.calculate_realized_pnl(symbol)
        unrealized = self.calculate_unrealized_pnl(symbol, current_price)
        
        # Calculate total fees/rebates from fills
        total_maker_rebate = 0.0
        total_taker_fees = 0.0
        
        if symbol in self.fills:
            for fill in self.fills[symbol]:
                if fill['is_maker']:
                    rebate = self.calculate_maker_rebate(fill['qty'], fill['price'], symbol)
                    total_maker_rebate += rebate
                else:
                    fees = self.calculate_taker_fees(fill['qty'], fill['price'], symbol)
                    total_taker_fees += fees
        
        return PnLBreakdown(
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            maker_rebate=total_maker_rebate,
            taker_fees=total_taker_fees
        )
    
    def get_inventory_summary(self) -> Dict[str, Dict]:
        """Get inventory summary for all symbols."""
        summary = {}
        for symbol in self.inventory:
            summary[symbol] = {
                'inventory': self.inventory[symbol],
                'avg_buy_price': self.avg_prices[symbol]['Buy'],
                'avg_sell_price': self.avg_prices[symbol]['Sell'],
                'realized_pnl': self.realized_pnl[symbol],
                'fill_count': len(self.fills.get(symbol, []))
            }
        return summary
    
    def reset_symbol(self, symbol: str):
        """Reset PnL tracking for a symbol."""
        if symbol in self.inventory:
            del self.inventory[symbol]
        if symbol in self.avg_prices:
            del self.avg_prices[symbol]
        if symbol in self.realized_pnl:
            del self.realized_pnl[symbol]
        if symbol in self.fills:
            del self.fills[symbol]
        
        logger.info(f"Reset PnL tracking for {symbol}")
    
    def get_metrics_update(self, symbol: str, current_price: float) -> Dict[str, float]:
        """Get metrics update for Prometheus."""
        pnl_breakdown = self.get_total_pnl(symbol, current_price)
        
        return {
            'maker_pnl': pnl_breakdown.maker_rebate,
            'taker_fees': pnl_breakdown.taker_fees,
            'realized_pnl': pnl_breakdown.realized_pnl,
            'unrealized_pnl': pnl_breakdown.unrealized_pnl,
            'total_pnl': pnl_breakdown.total_pnl,
            'inventory': self.inventory.get(symbol, 0.0)
        }

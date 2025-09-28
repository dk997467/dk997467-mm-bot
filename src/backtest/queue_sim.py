"""
Queue-based fill simulation for backtesting.

Provides FIFO approximation with ahead_volume calculation to emulate
realistic order fills in backtesting scenarios.
"""

import logging
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Set, Any
from decimal import Decimal
from dataclasses import dataclass

from src.common.models import OrderBook, PriceLevel, Side
from src.marketdata.orderbook import OrderBookAggregator

logger = logging.getLogger(__name__)


@dataclass
class CalibrationParams:
    """Calibration parameters for queue simulation."""
    latency_ms_mean: float = 0.0
    latency_ms_std: float = 0.0
    amend_latency_ms: float = 0.0
    cancel_latency_ms: float = 0.0
    toxic_sweep_prob: float = 0.0  # Probability of toxic sweep (0-1)
    extra_slippage_bps: float = 0.0  # Additional slippage in basis points
    
    def __post_init__(self):
        """Validate parameter ranges."""
        if self.toxic_sweep_prob < 0 or self.toxic_sweep_prob > 1:
            raise ValueError("toxic_sweep_prob must be between 0 and 1")
        if self.latency_ms_mean < 0 or self.latency_ms_std < 0:
            raise ValueError("Latency parameters must be non-negative")


@dataclass
class SimulatedOrder:
    """Simulated order for queue simulation."""
    order_id: str
    symbol: str
    side: Side
    price: Decimal
    qty: Decimal
    timestamp: datetime
    is_active: bool = True
    filled_qty: Decimal = Decimal('0')
    
    # E1: Additional timing fields for calibration
    submit_time: Optional[datetime] = None
    actual_place_time: Optional[datetime] = None  # After latency
    
    @property
    def remaining_qty(self) -> Decimal:
        """Get remaining quantity to fill."""
        return self.qty - self.filled_qty
    
    @property
    def queue_wait_ms(self) -> Optional[float]:
        """Calculate queue wait time in milliseconds."""
        if self.actual_place_time and self.filled_qty > 0:
            # Assume the fill happened "now" for this calculation
            # In practice, this would be updated when the fill actually occurs
            wait_time = (datetime.now(timezone.utc) - self.actual_place_time).total_seconds() * 1000
            return max(0, wait_time)
        return None


@dataclass
class SimulatedFill:
    """Simulated fill result."""
    order_id: str
    symbol: str
    side: Side
    fill_price: Decimal
    fill_qty: Decimal
    timestamp: datetime
    is_maker: bool = True
    fees: Decimal = Decimal('0')


class QueueSimulator:
    """Queue-based fill simulator for backtesting."""
    
    def __init__(self, orderbook_aggregator: OrderBookAggregator, 
                 calibration: Optional[CalibrationParams] = None):
        """Initialize queue simulator."""
        self.orderbook_aggregator = orderbook_aggregator
        self.calibration = calibration or CalibrationParams()
        
        # Active orders by symbol and side
        self.active_orders: Dict[str, Dict[str, List[SimulatedOrder]]] = {}  # symbol -> side -> orders
        
        # Fill history
        self.fills: List[SimulatedFill] = []
        
        # Statistics
        self.total_fills = 0
        self.maker_fills = 0
        self.taker_fills = 0
        
        # E1: Random number generator for calibration effects
        self.rng = random.Random()
        
        logger.info(f"Queue simulator initialized with calibration: {self.calibration}")
    
    def add_order(self, order: SimulatedOrder) -> bool:
        """Add an order to the simulation."""
        if order.symbol not in self.active_orders:
            self.active_orders[order.symbol] = {'Buy': [], 'Sell': []}
        
        # E1: Apply placement latency
        order.submit_time = order.timestamp
        placement_latency_ms = self._calculate_placement_latency()
        order.actual_place_time = order.timestamp + timedelta(milliseconds=placement_latency_ms)
        
        side_str = order.side.value
        self.active_orders[order.symbol][side_str].append(order)
        
        # Sort orders by price (best first for each side)
        if side_str == 'Buy':
            # Bids: highest price first
            self.active_orders[order.symbol][side_str].sort(key=lambda x: x.price, reverse=True)
        else:
            # Asks: lowest price first
            self.active_orders[order.symbol][side_str].sort(key=lambda x: x.price)
        
        logger.debug(f"Added order {order.order_id} to {order.symbol} {side_str} queue "
                    f"(latency: {placement_latency_ms:.1f}ms)")
        return True
    
    def _calculate_placement_latency(self) -> float:
        """Calculate order placement latency in milliseconds."""
        if self.calibration.latency_ms_std > 0:
            # Use normal distribution for latency
            latency = self.rng.gauss(self.calibration.latency_ms_mean, 
                                   self.calibration.latency_ms_std)
            return max(0, latency)
        else:
            return self.calibration.latency_ms_mean
    
    def _apply_extra_slippage(self, base_price: Decimal, mid_price: float) -> Decimal:
        """Apply additional slippage to fill price."""
        if self.calibration.extra_slippage_bps <= 0:
            return base_price
        
        # Convert bps to price adjustment
        slippage_factor = self.calibration.extra_slippage_bps / 10000
        adjustment = Decimal(str(mid_price * slippage_factor))
        
        # Negative slippage (worse price for us)
        return base_price - adjustment
    
    def _is_toxic_sweep(self) -> bool:
        """Determine if this is a toxic sweep based on probability."""
        return self.rng.random() < self.calibration.toxic_sweep_prob
    
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order from the simulation."""
        if symbol not in self.active_orders:
            return False
        
        for side in ['Buy', 'Sell']:
            orders = self.active_orders[symbol][side]
            for i, order in enumerate(orders):
                if order.order_id == order_id:
                    orders.pop(i)
                    logger.debug(f"Cancelled order {order_id} from {symbol} {side}")
                    return True
        
        return False
    
    def simulate_market_moves(self, orderbook: OrderBook) -> List[SimulatedFill]:
        """Simulate market moves and generate fills."""
        fills = []
        symbol = orderbook.symbol
        
        if symbol not in self.active_orders:
            return fills
        
        # Get current market prices
        if not orderbook.bids or not orderbook.asks:
            return fills
        
        best_bid = orderbook.bids[0].price
        best_ask = orderbook.asks[0].price
        
        # Check for fills on both sides
        fills.extend(self._check_bid_fills(symbol, best_ask))
        fills.extend(self._check_ask_fills(symbol, best_bid))
        
        # Update fill statistics
        for fill in fills:
            self.total_fills += 1
            if fill.is_maker:
                self.maker_fills += 1
            else:
                self.taker_fills += 1
        
        # Add to fill history
        self.fills.extend(fills)
        
        return fills
    
    def _check_bid_fills(self, symbol: str, best_ask: Decimal) -> List[SimulatedFill]:
        """Check for fills on bid orders when ask price drops."""
        fills = []
        bid_orders = self.active_orders[symbol]['Buy']
        
        # Check each bid order for potential fills
        for order in bid_orders[:]:  # Copy list to avoid modification during iteration
            if not order.is_active or order.remaining_qty <= 0:
                continue
            
            # E1: Check if order has been placed yet (latency check)
            now = datetime.now(timezone.utc)
            if order.actual_place_time and now < order.actual_place_time:
                continue  # Order not yet active due to latency
            
            # If our bid price >= best ask, we get filled
            if order.price >= best_ask:
                # E1: Check for toxic sweep
                if self._is_toxic_sweep():
                    # Toxic sweep - we become taker instead of maker
                    is_maker = False
                    fill_price = best_ask
                else:
                    is_maker = True
                    fill_price = best_ask
                
                # Calculate fill quantity (minimum of remaining qty and available ask volume)
                available_volume = self._get_available_volume(symbol, 'ask', best_ask)
                fill_qty = min(order.remaining_qty, available_volume)
                
                if fill_qty > 0:
                    # E1: Apply extra slippage
                    mid_price = float(best_ask)  # Simple approximation
                    final_fill_price = self._apply_extra_slippage(fill_price, mid_price)
                    
                    # Create fill
                    fill = SimulatedFill(
                        order_id=order.order_id,
                        symbol=symbol,
                        side=Side.BUY,
                        fill_price=final_fill_price,
                        fill_qty=fill_qty,
                        timestamp=now,
                        is_maker=is_maker
                    )
                    fills.append(fill)
                    
                    # Update order
                    order.filled_qty += fill_qty
                    if order.filled_qty >= order.qty:
                        order.is_active = False
                    
                    logger.debug(f"Bid fill: {order.order_id} filled {fill_qty} @ {final_fill_price} "
                               f"(maker: {is_maker})")
        
        return fills
    
    def _check_ask_fills(self, symbol: str, best_bid: Decimal) -> List[SimulatedFill]:
        """Check for fills on ask orders when bid price rises."""
        fills = []
        ask_orders = self.active_orders[symbol]['Sell']
        
        # Check each ask order for potential fills
        for order in ask_orders[:]:  # Copy list to avoid modification during iteration
            if not order.is_active or order.remaining_qty <= 0:
                continue
            
            # E1: Check if order has been placed yet (latency check)
            now = datetime.now(timezone.utc)
            if order.actual_place_time and now < order.actual_place_time:
                continue  # Order not yet active due to latency
            
            # If our ask price <= best bid, we get filled
            if order.price <= best_bid:
                # E1: Check for toxic sweep
                if self._is_toxic_sweep():
                    # Toxic sweep - we become taker instead of maker
                    is_maker = False
                    fill_price = best_bid
                else:
                    is_maker = True
                    fill_price = best_bid
                
                # Calculate fill quantity (minimum of remaining qty and available bid volume)
                available_volume = self._get_available_volume(symbol, 'bid', best_bid)
                fill_qty = min(order.remaining_qty, available_volume)
                
                if fill_qty > 0:
                    # E1: Apply extra slippage
                    mid_price = float(best_bid)  # Simple approximation
                    final_fill_price = self._apply_extra_slippage(fill_price, mid_price)
                    
                    # Create fill
                    fill = SimulatedFill(
                        order_id=order.order_id,
                        symbol=symbol,
                        side=Side.SELL,
                        fill_price=final_fill_price,
                        fill_qty=fill_qty,
                        timestamp=now,
                        is_maker=is_maker
                    )
                    fills.append(fill)
                    
                    # Update order
                    order.filled_qty += fill_qty
                    if order.filled_qty >= order.qty:
                        order.is_active = False
                    
                    logger.debug(f"Ask fill: {order.order_id} filled {fill_qty} @ {final_fill_price} "
                               f"(maker: {is_maker})")
        
        return fills
    
    def _get_available_volume(self, symbol: str, side: str, price: Decimal) -> Decimal:
        """Get available volume at a given price level."""
        try:
            # Use orderbook aggregator to get ahead volume
            ahead_vol = self.orderbook_aggregator.ahead_volume(symbol, side, float(price))
            return Decimal(str(ahead_vol))
        except Exception as e:
            logger.warning(f"Error getting ahead volume: {e}, using default")
            return Decimal('1.0')  # Default volume
    
    def get_queue_position(self, symbol: str, side: str, price: Decimal) -> int:
        """Get queue position for a given price level."""
        if symbol not in self.active_orders:
            return 0
        
        side_str = side.capitalize()
        if side_str not in self.active_orders[symbol]:
            return 0
        
        orders = self.active_orders[symbol][side_str]
        position = 0
        
        for order in orders:
            if not order.is_active:
                continue
            
            if side_str == 'Buy':
                # For bids, higher price = better position
                if order.price > price:
                    position += 1
                elif order.price == price:
                    return position
                else:
                    break
            else:
                # For asks, lower price = better position
                if order.price < price:
                    position += 1
                elif order.price == price:
                    return position
                else:
                    break
        
        return position
    
    def get_active_orders_summary(self, symbol: str) -> Dict[str, Any]:
        """Get summary of active orders for a symbol."""
        if symbol not in self.active_orders:
            return {'error': 'Symbol not found'}
        
        summary = {
            'symbol': symbol,
            'total_orders': 0,
            'orders_by_side': {},
            'total_notional': 0.0
        }
        
        for side in ['Buy', 'Sell']:
            orders = self.active_orders[symbol][side]
            active_orders = [o for o in orders if o.is_active and o.remaining_qty > 0]
            
            side_summary = {
                'count': len(active_orders),
                'total_qty': float(sum(o.remaining_qty for o in active_orders)),
                'avg_price': float(sum(o.price * o.remaining_qty for o in active_orders) / 
                                 sum(o.remaining_qty for o in active_orders)) if active_orders else 0.0
            }
            
            summary['orders_by_side'][side] = side_summary
            summary['total_orders'] += len(active_orders)
            summary['total_notional'] += sum(float(o.price * o.remaining_qty) for o in active_orders)
        
        return summary
    
    def get_fill_statistics(self) -> Dict[str, Any]:
        """Get fill statistics."""
        return {
            'total_fills': self.total_fills,
            'maker_fills': self.maker_fills,
            'taker_fills': self.taker_fills,
            'maker_ratio': self.maker_fills / self.total_fills if self.total_fills > 0 else 0.0,
            'total_fill_value': sum(float(f.fill_price * f.fill_qty) for f in self.fills),
            'calibration_params': {
                'latency_ms_mean': self.calibration.latency_ms_mean,
                'latency_ms_std': self.calibration.latency_ms_std,
                'amend_latency_ms': self.calibration.amend_latency_ms,
                'cancel_latency_ms': self.calibration.cancel_latency_ms,
                'toxic_sweep_prob': self.calibration.toxic_sweep_prob,
                'extra_slippage_bps': self.calibration.extra_slippage_bps
            }
        }
    
    def reset_symbol(self, symbol: str):
        """Reset simulation state for a symbol."""
        if symbol in self.active_orders:
            del self.active_orders[symbol]
        
        # Remove fills for this symbol
        self.fills = [f for f in self.fills if f.symbol != symbol]
        
        logger.info(f"Reset simulation state for {symbol}")
    
    def reset_all(self):
        """Reset all simulation state."""
        self.active_orders.clear()
        self.fills.clear()
        self.total_fills = 0
        self.maker_fills = 0
        self.taker_fills = 0
        
        logger.info("Reset all simulation state")

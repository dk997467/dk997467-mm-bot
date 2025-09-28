"""
Market making strategy with adaptive spreads and inventory management.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import numpy as np

# Helper function to convert to float for calculations
def F(x): return float(x) if isinstance(x, Decimal) else float(x)

from src.common.config import Config
from src.common.models import OrderBook, QuoteRequest, Side, Order, Trade
from src.common.utils import round_to_tick_size, round_to_lot_size, clamp


class MarketMakingStrategy:
    """Market making strategy with adaptive spreads and inventory management."""
    
    def __init__(self, config: Config, recorder=None, metrics_exporter=None):
        """Initialize the strategy."""
        self.config = config
        self.recorder = recorder
        self.metrics = metrics_exporter
        
        # Strategy state
        self.active_quotes: Dict[str, Dict[str, Dict]] = {}  # symbol -> side -> order_id -> quote_info
        self.inventory: Dict[str, Decimal] = {}  # symbol -> current inventory
        self.last_quote_time: Dict[str, datetime] = {}  # symbol -> last quote update
        self._last_quote: Dict[str, Tuple[int, Decimal]] = {}  # symbol -> (ts_ms, last_mid)
        
        # Performance tracking
        self.total_pnl = Decimal(0)
        self.realized_pnl = Decimal(0)
        self.unrealized_pnl = Decimal(0)
        self.total_trades = 0
        self.fill_rate = Decimal(0)
        
        # Strategy configuration with defaults
        self.k_vola = getattr(config.strategy, 'k_vola', 0.5)
        self.k_imb = getattr(config.strategy, 'k_imb', 0.2)
        self.t_imb = getattr(config.strategy, 't_imb', 0.1)
        self.risk_buffer_bps = getattr(config.strategy, 'risk_buffer_bps', 2.0)
        self.skew_k = getattr(config.strategy, 'skew_k', 0.1)
        self.max_skew_bps = getattr(config.strategy, 'max_skew_bps', 30.0)
        
        # Trading fees with defaults
        self.maker_fee_bps = getattr(config.trading, 'maker_fee_bps', 1.0)
        self.taker_fee_bps = getattr(config.trading, 'taker_fee_bps', 1.0)
        
        # Volatility tracking
        self.volatility_history: Dict[str, List[Decimal]] = {}
        self.volatility_threshold = Decimal("0.02")  # 2% volatility threshold
        
        # Callbacks
        self.on_quote_request = None
        self.on_strategy_update = None
        
        # Initialize inventory tracking
        for symbol in config.trading.symbols:
            self.inventory[symbol] = Decimal(0)
            self.volatility_history[symbol] = []
            self.active_quotes[symbol] = {"Buy": {}, "Sell": {}}
    
    def update_orderbook(self, symbol: str, orderbook: OrderBook):
        """Update strategy with new orderbook data."""
        try:
            # Record book snapshot if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_book_snapshot(orderbook))
            
            # Update volatility history
            mid_price = orderbook.mid_price
            if mid_price:
                self.volatility_history[symbol].append(mid_price)
                if len(self.volatility_history[symbol]) > 100:  # Keep last 100 prices
                    self.volatility_history[symbol].pop(0)
            
            # Check if we need to update quotes
            if self._should_update_quotes(symbol, orderbook):
                self._generate_quotes(symbol, orderbook)
                
        except Exception as e:
            print(f"Error updating strategy with orderbook: {e}")
    
    def update_inventory(self, symbol: str, side: Side, quantity: Decimal, price: Decimal):
        """Update inventory after a trade."""
        try:
            if side == Side.BUY:
                self.inventory[symbol] += quantity
            else:
                self.inventory[symbol] -= quantity
            
            # Update P&L
            trade_pnl = self._calculate_trade_pnl(symbol, side, quantity, price)
            self.total_pnl += trade_pnl
            self.realized_pnl += trade_pnl
            self.total_trades += 1
            
            # Update fill rate
            self._update_fill_rate()
            
            # Record inventory update if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "inventory_update",
                    {
                        "symbol": symbol,
                        "side": side.value,
                        "quantity": float(quantity),
                        "price": float(price),
                        "new_inventory": float(self.inventory[symbol]),
                        "trade_pnl": float(trade_pnl),
                        "timestamp": datetime.now(timezone.utc)
                    }
                ))
            
            # Trigger quote update if inventory changed significantly
            self._trigger_quote_update(symbol)
            
        except Exception as e:
            print(f"Error updating inventory: {e}")
    
    def record_new_quote(self, quote: QuoteRequest):
        """Record a new quote being generated."""
        if self.recorder:
            quote_data = {
                "symbol": quote.symbol,
                "side": quote.side.value,
                "qty": float(quote.qty),
                "price": float(quote.price),
                "post_only": quote.post_only,
                "time_in_force": quote.time_in_force.value,
                "timestamp": datetime.now(timezone.utc)
            }
            asyncio.create_task(self.recorder.record_quote(quote_data))
    
    def record_order_placement(self, order: Order):
        """Record when an order is placed."""
        if self.recorder:
            asyncio.create_task(self.recorder.record_order(order))
    
    def record_order_fill(self, fill: Trade):
        """Record when an order is filled."""
        if self.recorder:
            asyncio.create_task(self.recorder.record_fill(fill))
    
    def record_book_snapshot(self, orderbook: OrderBook):
        """Record a book snapshot."""
        if self.recorder:
            asyncio.create_task(self.recorder.record_book_snapshot(orderbook))
    
    def _should_update_quotes(self, symbol: str, orderbook: OrderBook) -> bool:
        """Check if quotes should be updated."""
        try:
            # Get current mid price and timestamp
            current_mid = orderbook.mid_price
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            quote_refresh_ms = getattr(self.config.strategy, 'quote_refresh_ms', 800)
            amend_threshold_bps = getattr(self.config.strategy, 'amend_price_threshold_bps', 1.0)
            
            # Check per-symbol refresh throttling
            if symbol in self._last_quote and current_mid:
                last_ts_ms, last_mid = self._last_quote[symbol]
                time_delta = now_ms - last_ts_ms
                
                if time_delta < quote_refresh_ms and last_mid > 0:
                    # Check price movement threshold
                    price_move_bps = abs(F(current_mid) - F(last_mid)) / F(last_mid) * 10000
                    if price_move_bps < amend_threshold_bps:
                        return False
            
            # Check volatility-based update
            volatility = self._get_current_volatility(symbol)
            if volatility and volatility > self.volatility_threshold:
                return True
            
            # Check spread-based update
            current_spread = None
            try:
                current_spread = orderbook.get_spread_bps()  # type: ignore[attr-defined]
            except Exception:
                pass
            if current_spread is None:
                try:
                    current_spread = orderbook.spread_bps  # type: ignore[attr-defined]
                except Exception:
                    current_spread = None
            if current_spread:
                base_spread = F(self.config.trading.base_spread_bps)
                if abs(F(current_spread) - base_spread) > 0.5:  # 0.5 bps threshold
                    return True
            
            return True
            
        except Exception as e:
            print(f"Error checking if quotes should update: {e}")
            return True
    
    def _generate_quotes(self, symbol: str, orderbook: OrderBook):
        """Generate new quotes for a symbol."""
        try:
            # Get fair value
            fair_value = self._calculate_fair_value(orderbook)
            if not fair_value:
                return
            
            # Calculate adaptive spread with fees and risk buffer
            spread_bps = self._calculate_adaptive_spread(symbol, orderbook)
            
            # Calculate inventory skew
            inventory_skew = self._calculate_inventory_skew(symbol, orderbook)
            
            # Generate quote levels (ensure at least one level)
            quotes = self._generate_quote_levels(
                symbol, fair_value, spread_bps, inventory_skew, orderbook
            )
            if not quotes:
                # Fallback: single minimal quote on each side
                half_spread = F(spread_bps) / 2.0
                bid = F(fair_value) * (1.0 - half_spread)
                ask = F(fair_value) * (1.0 + half_spread)
                qty = self._calculate_base_quantity(symbol, orderbook)
                if bid > 0 and qty > 0:
                    quotes.append(QuoteRequest(symbol=symbol, side=Side.BUY, qty=qty, price=Decimal(str(bid)), post_only=self.config.trading.post_only))
                if ask > 0 and qty > 0:
                    quotes.append(QuoteRequest(symbol=symbol, side=Side.SELL, qty=qty, price=Decimal(str(ask)), post_only=self.config.trading.post_only))
            
            # Record each quote
            for quote in quotes:
                self.record_new_quote(quote)
            
            # Update metrics for quote generation
            if self.metrics and quotes:
                self.metrics.increment_quotes_generated(str(symbol))
            
            # Send quote requests
            for quote in quotes:
                if self.on_quote_request:
                    self.on_quote_request(quote)
            
            # Update state
            self.last_quote_time[symbol] = datetime.now(timezone.utc)
            
            # Update throttling state
            current_mid = orderbook.mid_price
            if current_mid:
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                self._last_quote[symbol] = (now_ms, current_mid)
            
            # Record quote generation if recorder is available
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "quote_generation",
                    {
                        "symbol": symbol,
                        "num_quotes": len(quotes),
                        "fair_value": float(fair_value) if fair_value else None,
                        "spread_bps": float(spread_bps),
                        "inventory_skew": float(inventory_skew),
                        "timestamp": datetime.now(timezone.utc)
                    }
                ))
            
            # Call strategy update callback
            if self.on_strategy_update:
                self.on_strategy_update(symbol, quotes)
                
        except Exception as e:
            print(f"Error generating quotes: {e}")
    
    def _calculate_fair_value(self, orderbook: OrderBook) -> Optional[Decimal]:
        """Calculate fair value using microprice and imbalance."""
        try:
            mid_price = F(orderbook.mid_price)
            if not mid_price:
                return None
            
            # Calculate microprice (fallback to mid_price if not available)
            microprice = None
            try:
                microprice = F(orderbook.get_microprice())  # type: ignore[attr-defined]
            except Exception:
                microprice = None
            if not microprice:
                microprice = mid_price
            
            # Calculate imbalance (fallback to 0 if not available)
            imbalance = None
            try:
                imbalance = F(orderbook.get_imbalance())  # type: ignore[attr-defined]
            except Exception:
                imbalance = None
            if imbalance is None:
                imbalance = 0.0
            
            # Weighted combination
            imbalance_weight = F(self.config.strategy.imbalance_weight)
            microprice_weight = F(self.config.strategy.microprice_weight)
            
            fair_value = (
                mid_price * (1.0 - imbalance_weight - microprice_weight) +
                microprice * microprice_weight +
                (mid_price * (1.0 + imbalance)) * imbalance_weight
            )
            
            return Decimal(str(fair_value))
            
        except Exception as e:
            print(f"Error calculating fair value: {e}")
            return orderbook.mid_price
    
    def _calculate_adaptive_spread(self, symbol: str, orderbook: OrderBook) -> Decimal:
        """Calculate adaptive spread based on market conditions with fees and risk buffer."""
        try:
            # Base spread from volatility and imbalance
            vola_5m_bps = self._get_current_volatility(symbol) or 0.0
            vola_5m_bps = F(vola_5m_bps) * 10000.0  # Convert to bps
            
            # Get imbalance (fallback to 0)
            imb_10 = 0.0
            try:
                imb_10 = F(orderbook.get_imbalance())  # type: ignore[attr-defined]
            except Exception:
                pass
            
            # Calculate base spread: k_vola*vola_5m_bps + k_imb*max(0, abs(imb_10) - t_imb)
            base_bps = (
                self.k_vola * vola_5m_bps + 
                self.k_imb * max(0.0, abs(imb_10) - self.t_imb)
            )
            
            # Edge spread: max(base_bps, maker_fee_bps + taker_fee_bps + risk_buffer_bps)
            edge_bps = max(
                base_bps,
                self.maker_fee_bps + self.taker_fee_bps + self.risk_buffer_bps
            )
            
            # Log structured decision data
            if self.recorder:
                asyncio.create_task(self.recorder.record_custom_event(
                    "spread_calculation",
                    {
                        "symbol": symbol,
                        "vola_5m_bps": vola_5m_bps,
                        "imb_10": imb_10,
                        "base_bps": base_bps,
                        "edge_bps": edge_bps,
                        "maker_fee_bps": self.maker_fee_bps,
                        "taker_fee_bps": self.taker_fee_bps,
                        "risk_buffer_bps": self.risk_buffer_bps,
                        "timestamp": datetime.now(timezone.utc)
                    }
                ))
            
            return Decimal(str(edge_bps / 10000.0))
            
        except Exception as e:
            print(f"Error calculating adaptive spread: {e}")
            return Decimal(str(F(self.config.trading.base_spread_bps) / 10000.0))
    
    def _calculate_inventory_skew(self, symbol: str, orderbook: OrderBook) -> Decimal:
        """Calculate inventory skew adjustment using new parameters."""
        try:
            current_inventory = F(self.inventory.get(symbol, Decimal(0)))
            target_inventory = F(self.config.risk.target_inventory_usd)
            
            # Calculate skew based on inventory difference
            inventory_diff = current_inventory - target_inventory
            
            # Apply skew coefficient: skew_bps = clamp(skew_k * (position - target), -max_skew_bps, +max_skew_bps)
            skew_bps = self.skew_k * inventory_diff
            
            # Clamp to maximum skew bounds
            skew_bps = max(-self.max_skew_bps, min(self.max_skew_bps, skew_bps))
            
            # Convert to decimal ratio
            return Decimal(str(skew_bps / 10000.0))
            
        except Exception as e:
            print(f"Error calculating inventory skew: {e}")
            return Decimal("0")
    
    def _generate_quote_levels(
        self, 
        symbol: str, 
        fair_value: Decimal, 
        spread_bps: Decimal, 
        inventory_skew: Decimal,
        orderbook: OrderBook
    ) -> List[QuoteRequest]:
        """Generate quote levels for both sides using microprice centering."""
        try:
            quotes = []
            
            # Use microprice for centering (fallback to fair_value)
            center_price = None
            try:
                center_price = F(orderbook.get_microprice())  # type: ignore[attr-defined]
            except Exception:
                center_price = F(fair_value)
            
            if not center_price:
                center_price = F(fair_value)
            
            # Calculate skew adjustment: skew_bps = clamp(skew_k * (position - target), -max_skew_bps, +max_skew_bps)
            skew_bps = F(inventory_skew) * 10000.0  # Convert back to bps
            
            # Apply inventory skew to spread: bid = center * (1 - (edge_bps - skew_bps)/10000), ask = center * (1 + (edge_bps + skew_bps)/10000)
            edge_bps = F(spread_bps) * 10000.0
            bid = center_price * (1.0 - (edge_bps - skew_bps) / 10000.0)
            ask = center_price * (1.0 + (edge_bps + skew_bps) / 10000.0)
            
            # Generate ladder levels with configurable max levels
            max_quote_levels = getattr(self.config.strategy, 'max_quote_levels', 3)
            ladder_levels = min(self.config.trading.ladder_levels, max_quote_levels)
            
            for level in range(ladder_levels):
                # Calculate level prices
                level_step = F(self.config.trading.ladder_step_bps) / 10000.0
                level_multiplier = float(level)
                
                bid_price = bid * (1.0 - level_step * level_multiplier)
                ask_price = ask * (1.0 + level_step * level_multiplier)
                
                # Round to tick size (would need instrument config)
                # bid_price = round_to_tick_size(bid_price, tick_size)
                # ask_price = round_to_tick_size(ask_price, tick_size)
                
                # Calculate quantities
                base_qty = self._calculate_base_quantity(symbol, orderbook)
                level_qty = F(base_qty) * (1.0 - float(level) * 0.2)  # Decrease size for deeper levels
                
                # Round to lot size (would need instrument config)
                # level_qty = round_to_lot_size(level_qty, lot_size)
                
                # Create quote requests
                if bid_price > 0 and level_qty > 0:
                    bid_quote = QuoteRequest(
                        symbol=symbol,
                        side=Side.BUY,
                        qty=Decimal(str(level_qty)),
                        price=Decimal(str(bid_price)),
                        post_only=self.config.trading.post_only
                    )
                    quotes.append(bid_quote)
                
                if ask_price > 0 and level_qty > 0:
                    ask_quote = QuoteRequest(
                        symbol=symbol,
                        side=Side.SELL,
                        qty=Decimal(str(level_qty)),
                        price=Decimal(str(ask_price)),
                        post_only=self.config.trading.post_only
                    )
                    quotes.append(ask_quote)
            
            return quotes
            
        except Exception as e:
            print(f"Error generating quote levels: {e}")
            return []
    
    def _calculate_base_quantity(self, symbol: str, orderbook: OrderBook) -> Decimal:
        """Calculate base quantity for quotes."""
        try:
            # Get minimum notional
            min_notional = F(self.config.trading.min_notional_usd)
            
            # Use mid price to calculate quantity
            mid_price = F(orderbook.mid_price)
            if not mid_price:
                return Decimal("0.001")  # Default small quantity
            
            base_qty = min_notional / mid_price
            
            # Ensure reasonable size
            min_qty = 0.001
            max_qty = 1.0
            
            return Decimal(str(clamp(base_qty, min_qty, max_qty)))
            
        except Exception as e:
            print(f"Error calculating base quantity: {e}")
            return Decimal("0.001")
    
    def _get_current_volatility(self, symbol: str) -> Optional[Decimal]:
        """Get current volatility for a symbol."""
        try:
            prices = self.volatility_history.get(symbol, [])
            if len(prices) < 2:
                return None
            
            # Calculate rolling volatility
            lookback = min(len(prices), self.config.strategy.volatility_lookback_sec)
            recent_prices = prices[-lookback:]
            
            if len(recent_prices) < 2:
                return None
            
            # Calculate returns and volatility
            returns = []
            for i in range(1, len(recent_prices)):
                if recent_prices[i-1] > 0:
                    ret = (F(recent_prices[i]) - F(recent_prices[i-1])) / F(recent_prices[i-1])
                    returns.append(ret)
            
            if not returns:
                return None
            
            # Calculate standard deviation
            volatility = np.std(returns)
            return Decimal(str(volatility))
            
        except Exception as e:
            print(f"Error calculating volatility: {e}")
            return None
    
    def _get_fill_adjustment_factor(self, symbol: str) -> Decimal:
        """Get fill rate adjustment factor."""
        try:
            # Adjust spread based on fill rate
            if F(self.fill_rate) > 0.8:  # High fill rate
                return Decimal("1.2")  # Widen spread
            elif F(self.fill_rate) < 0.2:  # Low fill rate
                return Decimal("0.8")  # Tighten spread
            else:
                return Decimal("1.0")  # No adjustment
                
        except Exception as e:
            print(f"Error getting fill adjustment factor: {e}")
            return Decimal("1.0")
    
    def _calculate_trade_pnl(self, symbol: str, side: Side, quantity: Decimal, price: Decimal) -> Decimal:
        """Calculate P&L for a trade."""
        try:
            # Get average price for the side we're trading against
            if side == Side.BUY:
                # We're buying, so compare against our average sell price
                avg_price = self._get_avg_short_price(symbol)
                if avg_price > 0:
                    return (avg_price - price) * quantity
            else:
                # We're selling, so compare against our average buy price
                avg_price = self._get_avg_long_price(symbol)
                if avg_price > 0:
                    return (price - avg_price) * quantity
            
            return Decimal("0")
            
        except Exception as e:
            print(f"Error calculating trade P&L: {e}")
            return Decimal("0")
    
    def _get_avg_long_price(self, symbol: str) -> Decimal:
        """Get average long position price."""
        # This would need to track individual trade prices
        # For now, return a placeholder
        return Decimal("0")
    
    def _get_avg_short_price(self, symbol: str) -> Decimal:
        """Get average short position price."""
        # This would need to track individual trade prices
        # For now, return a placeholder
        return Decimal("0")
    
    def _update_fill_rate(self):
        """Update fill rate based on recent activity."""
        try:
            # Simple moving average of fill rate
            # In a real implementation, this would track actual fills vs orders
            if self.total_trades > 0:
                # Placeholder calculation
                self.fill_rate = Decimal("0.5")  # 50% default
            else:
                self.fill_rate = Decimal("0")
                
        except Exception as e:
            print(f"Error updating fill rate: {e}")
    
    def _trigger_quote_update(self, symbol: str):
        """Trigger immediate quote update for a symbol."""
        try:
            # Reset last quote time to force update
            self.last_quote_time[symbol] = datetime.now(timezone.utc) - timedelta(seconds=1)
            
        except Exception as e:
            print(f"Error triggering quote update: {e}")
    
    def get_strategy_state(self) -> Dict:
        """Get current strategy state."""
        try:
            return {
                "active_quotes": {
                    symbol: {
                        side: len(quotes) for side, quotes in side_quotes.items()
                    }
                    for symbol, side_quotes in self.active_quotes.items()
                },
                "inventory": {
                    symbol: str(inv) for symbol, inv in self.inventory.items()
                },
                "performance": {
                    "total_pnl": str(self.total_pnl),
                    "realized_pnl": str(self.realized_pnl),
                    "unrealized_pnl": str(self.unrealized_pnl),
                    "total_trades": self.total_trades,
                    "fill_rate": str(self.fill_rate)
                },
                "volatility": {
                    symbol: str(self._get_current_volatility(symbol) or 0)
                    for symbol in self.config.trading.symbols
                },
                "last_quote_times": {
                    symbol: last_time.isoformat() if last_time else None
                    for symbol, last_time in self.last_quote_time.items()
                }
            }
            
        except Exception as e:
            print(f"Error getting strategy state: {e}")
            return {}
    
    def reset(self):
        """Reset strategy state."""
        try:
            # Reset state
            self.active_quotes.clear()
            self.inventory.clear()
            self.last_quote_time.clear()
            self.volatility_history.clear()
            
            # Reset performance
            self.total_pnl = Decimal("0")
            self.realized_pnl = Decimal("0")
            self.unrealized_pnl = Decimal("0")
            self.total_trades = 0
            self.fill_rate = Decimal("0")
            
            # Reinitialize
            for symbol in self.config.trading.symbols:
                self.inventory[symbol] = Decimal("0")
                self.volatility_history[symbol] = []
                self.active_quotes[symbol] = {"Buy": {}, "Sell": {}}
            
            print("Strategy state reset")
            
        except Exception as e:
            print(f"Error resetting strategy: {e}")
    
    def set_callbacks(self, on_quote_request=None, on_strategy_update=None):
        """Set strategy callbacks."""
        self.on_quote_request = on_quote_request
        self.on_strategy_update = on_strategy_update

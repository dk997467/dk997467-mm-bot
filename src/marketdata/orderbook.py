"""
Orderbook manager for maintaining Level 2 order book state.
"""

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import numpy as np

# Import Rust-backed L2Book
try:
    from mm_orderbook import L2Book
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    print("Warning: mm_orderbook not available, using Python fallback")

try:
    from common.models import OrderBook, PriceLevel
    from common.utils import calculate_imbalance, calculate_volatility
except ImportError:
    from src.common.models import OrderBook, PriceLevel
    from src.common.utils import calculate_imbalance, calculate_volatility


class OrderBookManager:
    """Manages Level 2 order book state with sequence validation and gap detection."""
    
    def __init__(self, symbol: str, max_depth: int = 25, recorder=None):
        """Initialize the orderbook manager."""
        self.symbol = symbol
        self.max_depth = max_depth
        self.recorder = recorder
        
        # Use Rust-backed L2Book if available, otherwise Python fallback
        if RUST_AVAILABLE:
            self.l2_book = L2Book()
            self.use_rust = True
        else:
            self.use_rust = False
            # Python fallback implementation
            self.bids: Dict[Decimal, Decimal] = {}  # price -> size
            self.asks: Dict[Decimal, Decimal] = {}  # price -> size
        
        # Sequence tracking
        self.last_sequence = 0
        self.sequence_gaps = 0
        self.last_update_time = datetime.now(timezone.utc)
        
        # Price history for volatility calculation
        self.mid_prices = deque(maxlen=1000)
        self.volatility_lookback = 30
        
        # Statistics
        self.update_count = 0
        self.snapshot_count = 0
        self.delta_count = 0
        
        # State flags
        self.is_synced = False
        self.needs_resync = False
        
        # Callbacks
        self.on_orderbook_update = None
        self.on_gap_detected = None
    
    def record_book_snapshot(self, orderbook: OrderBook):
        """Record a book snapshot asynchronously."""
        if self.recorder:
            asyncio.create_task(self.recorder.record_book_snapshot(orderbook))
    
    def update_from_snapshot(self, orderbook: OrderBook) -> bool:
        """Update orderbook from a full snapshot."""
        try:
            # Validate sequence
            if self.is_synced and orderbook.sequence <= self.last_sequence:
                return False
            
            if self.use_rust:
                # Use Rust-backed L2Book
                bids = [(float(level.price), float(level.size)) for level in orderbook.bids]
                asks = [(float(level.price), float(level.size)) for level in orderbook.asks]
                self.l2_book.apply_snapshot(bids, asks)
            else:
                # Python fallback
                self.bids.clear()
                self.asks.clear()
                
                # Update bids
                for level in orderbook.bids:
                    if level.size > 0:
                        self.bids[level.price] = level.size
                
                # Update asks
                for level in orderbook.asks:
                    if level.size > 0:
                        self.asks[level.price] = level.size
            
            # Update state
            self.last_sequence = orderbook.sequence
            self.last_update_time = orderbook.timestamp
            self.is_synced = True
            self.needs_resync = False
            self.snapshot_count += 1
            
            # Record book snapshot
            self.record_book_snapshot(orderbook)
            
            # Update mid price history
            mid_price = self.get_mid_price()
            if mid_price:
                self.mid_prices.append(mid_price)
            
            # Call callback
            if self.on_orderbook_update:
                self.on_orderbook_update(self.get_orderbook())
            
            return True
            
        except Exception as e:
            print(f"Error updating orderbook from snapshot: {e}")
            return False
    
    def update_from_delta(self, delta_data: Dict) -> bool:
        """Update orderbook from incremental delta."""
        try:
            sequence = delta_data.get("u", 0)
            
            # Check for sequence gaps
            if self.is_synced:
                expected_sequence = self.last_sequence + 1
                if sequence != expected_sequence:
                    print(f"Sequence gap detected: expected {expected_sequence}, got {sequence}")
                    self.sequence_gaps += 1
                    self.needs_resync = True
                    
                    if self.on_gap_detected:
                        self.on_gap_detected(sequence, expected_sequence)
                    
                    return False
            
            if self.use_rust:
                # Use Rust-backed L2Book
                bids = []
                asks = []
                
                if "b" in delta_data:  # Bid updates
                    for bid in delta_data["b"]:
                        price = float(bid[0])
                        size = float(bid[1])
                        bids.append((price, size))
                
                if "a" in delta_data:  # Ask updates
                    for ask in delta_data["a"]:
                        price = float(ask[0])
                        size = float(ask[1])
                        asks.append((price, size))
                
                self.l2_book.apply_delta(bids, asks)
            else:
                # Python fallback
                # Apply delta updates
                if "b" in delta_data:  # Bid updates
                    for bid in delta_data["b"]:
                        price = Decimal(str(bid[0]))
                        size = Decimal(str(bid[1]))
                        
                        if size > 0:
                            self.bids[price] = size
                        else:
                            self.bids.pop(price, None)
                
                if "a" in delta_data:  # Ask updates
                    for ask in delta_data["a"]:
                        price = Decimal(str(ask[0]))
                        size = Decimal(str(ask[1]))
                        
                        if size > 0:
                            self.asks[price] = size
                        else:
                            self.asks.pop(price, None)
            
            # Update state
            self.last_sequence = sequence
            self.last_update_time = datetime.now(timezone.utc)
            self.delta_count += 1
            
            # Update mid price history
            mid_price = self.get_mid_price()
            if mid_price:
                self.mid_prices.append(mid_price)
            
            # Call callback
            if self.on_orderbook_update:
                self.on_orderbook_update(self.get_orderbook())
            
            return True
            
        except Exception as e:
            print(f"Error updating orderbook from delta: {e}")
            return False
    
    def get_orderbook(self) -> OrderBook:
        """Get current orderbook state."""
        if self.use_rust:
            # Get data from Rust-backed L2Book
            best_bid = self.l2_book.best_bid
            best_ask = self.l2_book.best_ask
            
            # Create PriceLevel objects for the interface
            bid_levels = []
            ask_levels = []
            
            if best_bid:
                bid_levels.append(PriceLevel(
                    price=Decimal(str(best_bid[0])),
                    size=Decimal(str(best_bid[1])),
                    sequence=self.last_sequence
                ))
            
            if best_ask:
                ask_levels.append(PriceLevel(
                    price=Decimal(str(best_ask[0])),
                    size=Decimal(str(best_ask[1])),
                    sequence=self.last_sequence
                ))
            
            return OrderBook(
                symbol=self.symbol,
                timestamp=self.last_update_time,
                sequence=self.last_sequence,
                bids=bid_levels,
                asks=ask_levels
            )
        else:
            # Python fallback
            # Sort bids (descending) and asks (ascending)
            sorted_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)
            sorted_asks = sorted(self.asks.items(), key=lambda x: x[0])
            
            # Convert to PriceLevel objects
            bid_levels = [
                PriceLevel(price=price, size=size, sequence=self.last_sequence)
                for price, size in sorted_bids[:self.max_depth]
            ]
            
            ask_levels = [
                PriceLevel(price=price, size=size, sequence=self.last_sequence)
                for price, size in sorted_asks[:self.max_depth]
            ]
            
            return OrderBook(
                symbol=self.symbol,
                timestamp=self.last_update_time,
                sequence=self.last_sequence,
                bids=bid_levels,
                asks=ask_levels
            )
    
    def get_mid_price(self) -> Optional[Decimal]:
        """Get current mid price."""
        if self.use_rust:
            mid = self.l2_book.mid()
            return Decimal(str(mid)) if mid is not None else None
        else:
            # Python fallback
            if not self.bids or not self.asks:
                return None
            
            best_bid = max(self.bids.keys())
            best_ask = min(self.asks.keys())
            
            return (best_bid + best_ask) / 2
    
    def get_spread(self) -> Optional[Decimal]:
        """Get current spread."""
        if self.use_rust:
            best_bid = self.l2_book.best_bid
            best_ask = self.l2_book.best_ask
            
            if best_bid and best_ask:
                return Decimal(str(best_ask[0] - best_bid[0]))
            return None
        else:
            # Python fallback
            if not self.bids or not self.asks:
                return None
            
            best_bid = max(self.bids.keys())
            best_ask = min(self.asks.keys())
            
            return best_ask - best_bid
    
    def get_spread_bps(self) -> Optional[Decimal]:
        """Get current spread in basis points."""
        mid_price = self.get_mid_price()
        spread = self.get_spread()
        
        if mid_price and spread:
            return (spread / mid_price) * 10000
        return None
    
    def get_microprice(self) -> Optional[Decimal]:
        """Calculate microprice based on order book imbalance."""
        if self.use_rust:
            micro = self.l2_book.microprice()
            return Decimal(str(micro)) if micro is not None else None
        else:
            # Python fallback
            if not self.bids or not self.asks:
                return None
            
            best_bid = max(self.bids.keys())
            best_ask = min(self.asks.keys())
            best_bid_size = self.bids[best_bid]
            best_ask_size = self.asks[best_ask]
            
            total_size = best_bid_size + best_ask_size
            if total_size == 0:
                return self.get_mid_price()
            
            bid_weight = best_ask_size / total_size
            ask_weight = best_bid_size / total_size
            
            return best_bid * bid_weight + best_ask * ask_weight
    
    def get_imbalance(self, depth: int = 5) -> Optional[Decimal]:
        """Calculate order book imbalance."""
        if self.use_rust:
            imbalance = self.l2_book.imbalance(depth)
            return Decimal(str(imbalance))
        else:
            # Python fallback
            if not self.bids or not self.asks:
                return None
            
            bid_volume = sum(self.bids.values())
            ask_volume = sum(self.asks.values())
            total_volume = bid_volume + ask_volume
            
            if total_volume == 0:
                return Decimal(0)
            
            return (bid_volume - ask_volume) / total_volume
    
    def get_volatility(self, lookback_periods: Optional[int] = None) -> Optional[Decimal]:
        """Calculate volatility using mid price returns."""
        if len(self.mid_prices) < 2:
            return None
        
        lookback = lookback_periods or self.volatility_lookback
        prices = list(self.mid_prices)[-lookback:]
        
        if len(prices) < 2:
            return None
        
        # Calculate returns and volatility
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                ret = (prices[i] - prices[i-1]) / prices[i-1]
                returns.append(float(ret))
        
        if not returns:
            return None
        
        # Calculate standard deviation
        volatility = np.std(returns)
        return Decimal(str(volatility))
    
    def get_depth_at_price(self, price: Decimal, side: str) -> Decimal:
        """Get total depth at a specific price level."""
        if self.use_rust:
            # For Rust implementation, we need to check if the price exists
            if side.upper() == "BID":
                best_bid = self.l2_book.best_bid
                if best_bid and abs(best_bid[0] - float(price)) < 1e-10:
                    return Decimal(str(best_bid[1]))
            elif side.upper() == "ASK":
                best_ask = self.l2_book.best_ask
                if best_ask and abs(best_ask[0] - float(price)) < 1e-10:
                    return Decimal(str(best_ask[1]))
            return Decimal(0)
        else:
            # Python fallback
            if side.upper() == "BID":
                return self.bids.get(price, Decimal(0))
            elif side.upper() == "ASK":
                return self.asks.get(price, Decimal(0))
            else:
                return Decimal(0)
    
    def get_total_depth(self, side: str, levels: int = 5) -> Decimal:
        """Get total depth for first N levels on a side."""
        if self.use_rust:
            # For Rust implementation, we only have best bid/ask
            if levels == 1:
                if side.upper() == "BID":
                    best_bid = self.l2_book.best_bid
                    return Decimal(str(best_bid[1])) if best_bid else Decimal(0)
                elif side.upper() == "ASK":
                    best_ask = self.l2_book.best_ask
                    return Decimal(str(best_ask[1])) if best_ask else Decimal(0)
            return Decimal(0)
        else:
            # Python fallback
            if side.upper() == "BID":
                sorted_prices = sorted(self.bids.keys(), reverse=True)[:levels]
                return sum(self.bids[price] for price in sorted_prices)
            elif side.upper() == "ASK":
                sorted_prices = sorted(self.asks.keys())[:levels]
                return sum(self.asks[price] for price in sorted_prices)
            else:
                return Decimal(0)
    
    def get_price_levels(self, side: str, levels: int = 5) -> List[Tuple[Decimal, Decimal]]:
        """Get price levels with sizes for a side."""
        if self.use_rust:
            # For Rust implementation, we only have best bid/ask
            if levels >= 1:
                if side.upper() == "BID":
                    best_bid = self.l2_book.best_bid
                    if best_bid:
                        return [(Decimal(str(best_bid[0])), Decimal(str(best_bid[1])))]
                elif side.upper() == "ASK":
                    best_ask = self.l2_book.best_ask
                    if best_ask:
                        return [(Decimal(str(best_ask[0])), Decimal(str(best_ask[1])))]
            return []
        else:
            # Python fallback
            if side.upper() == "BID":
                sorted_items = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:levels]
            elif side.upper() == "ASK":
                sorted_items = sorted(self.asks.items(), key=lambda x: x[0])[:levels]
            else:
                return []
            
            return [(price, size) for price, size in sorted_items]
    
    def is_crossed(self) -> bool:
        """Check if order book is crossed (bids > asks)."""
        if self.use_rust:
            best_bid = self.l2_book.best_bid
            best_ask = self.l2_book.best_ask
            
            if best_bid and best_ask:
                return best_bid[0] >= best_ask[0]
            return False
        else:
            # Python fallback
            if not self.bids or not self.asks:
                return False
            
            best_bid = max(self.bids.keys())
            best_ask = min(self.asks.keys())
            
            return best_bid >= best_ask
    
    def get_stats(self) -> Dict:
        """Get orderbook statistics."""
        return {
            "symbol": self.symbol,
            "is_synced": self.is_synced,
            "needs_resync": self.needs_resync,
            "last_sequence": self.last_sequence,
            "sequence_gaps": self.sequence_gaps,
            "update_count": self.update_count,
            "snapshot_count": self.snapshot_count,
            "delta_count": self.delta_count,
            "last_update_time": self.last_update_time.isoformat(),
            "implementation": "rust" if self.use_rust else "python",
            "mid_price": str(self.get_mid_price()) if self.get_mid_price() else None,
            "spread_bps": str(self.get_spread_bps()) if self.get_spread_bps() else None,
            "imbalance": str(self.get_imbalance()) if self.get_imbalance() else None,
            "volatility": str(self.get_volatility()) if self.get_volatility() else None
        }
    
    def reset(self):
        """Reset orderbook state."""
        if self.use_rust:
            self.l2_book.clear()
        else:
            self.bids.clear()
            self.asks.clear()
        
        self.last_sequence = 0
        self.sequence_gaps = 0
        self.is_synced = False
        self.needs_resync = False
        self.update_count = 0
        self.snapshot_count = 0
        self.delta_count = 0
        self.mid_prices.clear()
    
    def validate_integrity(self) -> bool:
        """Validate orderbook integrity."""
        try:
            # Check for crossed order book
            if self.is_crossed():
                print(f"Order book crossed for {self.symbol}")
                return False
            
            if not self.use_rust:
                # Python fallback validation
                # Check for negative sizes
                for price, size in self.bids.items():
                    if size < 0:
                        print(f"Negative bid size at {price}: {size}")
                        return False
                
                for price, size in self.asks.items():
                    if size < 0:
                        print(f"Negative ask size at {price}: {size}")
                        return False
                
                # Check price ordering
                if len(self.bids) > 1:
                    bid_prices = sorted(self.bids.keys(), reverse=True)
                    for i in range(1, len(bid_prices)):
                        if bid_prices[i] >= bid_prices[i-1]:
                            print(f"Bid prices not properly ordered: {bid_prices[i]} >= {bid_prices[i-1]}")
                            return False
                
                if len(self.asks) > 1:
                    ask_prices = sorted(self.asks.keys())
                    for i in range(1, len(ask_prices)):
                        if ask_prices[i] <= ask_prices[i-1]:
                            print(f"Ask prices not properly ordered: {ask_prices[i]} <= {ask_prices[i-1]}")
                            return False
            
            return True
            
        except Exception as e:
            print(f"Error validating orderbook integrity: {e}")
            return False


class OrderBookAggregator:
    """Aggregates orderbooks from multiple symbols."""
    
    def __init__(self, recorder=None):
        """Initialize the aggregator."""
        self.orderbooks: Dict[str, OrderBookManager] = {}
        self.callbacks = {}
        self.recorder = recorder
    
    def add_symbol(self, symbol: str, max_depth: int = 25):
        """Add a symbol to track."""
        if symbol not in self.orderbooks:
            self.orderbooks[symbol] = OrderBookManager(symbol, max_depth, self.recorder)
    
    def remove_symbol(self, symbol: str):
        """Remove a symbol from tracking."""
        if symbol in self.orderbooks:
            del self.orderbooks[symbol]
    
    def get_orderbook(self, symbol: str) -> Optional[OrderBook]:
        """Get orderbook for a symbol."""
        if symbol in self.orderbooks:
            return self.orderbooks[symbol].get_orderbook()
        return None
    
    def get_all_orderbooks(self) -> Dict[str, OrderBook]:
        """Get all orderbooks."""
        return {
            symbol: obm.get_orderbook()
            for symbol, obm in self.orderbooks.items()
        }
    
    def update_orderbook(self, symbol: str, orderbook: OrderBook) -> bool:
        """Update orderbook for a symbol."""
        if symbol not in self.orderbooks:
            self.add_symbol(symbol)
        
        # Record orderbook snapshot if recorder is available
        if self.recorder:
            asyncio.create_task(self.recorder.record_book_snapshot(orderbook))
        
        return self.orderbooks[symbol].update_from_snapshot(orderbook)
    
    def update_delta(self, symbol: str, delta_data: Dict) -> bool:
        """Update orderbook delta for a symbol."""
        if symbol not in self.orderbooks:
            return False
        
        return self.orderbooks[symbol].update_from_delta(delta_data)
    
    def record_snapshot_manually(self, symbol: str, orderbook: OrderBook):
        """Manually record a book snapshot for a symbol."""
        if self.recorder:
            asyncio.create_task(self.recorder.record_book_snapshot(orderbook))
    
    def record_all_snapshots(self):
        """Record snapshots for all tracked symbols."""
        if not self.recorder:
            return
        
        for symbol, obm in self.orderbooks.items():
            if obm.is_synced:
                current_orderbook = obm.get_orderbook()
                asyncio.create_task(self.recorder.record_book_snapshot(current_orderbook))
    
    def get_stats(self) -> Dict:
        """Get aggregated statistics."""
        stats = {}
        for symbol, obm in self.orderbooks.items():
            stats[symbol] = obm.get_stats()
        return stats
    
    def is_all_synced(self) -> bool:
        """Check if all orderbooks are synced."""
        return all(obm.is_synced for obm in self.orderbooks.values())
    
    def get_synced_symbols(self) -> List[str]:
        """Get list of synced symbols."""
        return [symbol for symbol, obm in self.orderbooks.items() if obm.is_synced]
    
    def ahead_volume(self, symbol: str, side: str, price: float) -> float:
        """
        Calculate volume ahead of our order at specified price.
        
        Args:
            symbol: Trading symbol
            side: 'bid' or 'ask'
            price: Our order price
            
        Returns:
            Volume ahead of our order in the queue
        """
        if symbol not in self.orderbooks:
            return 0.0
            
        obm = self.orderbooks[symbol]
        target_price = Decimal(str(price))
        
        if side.lower() == 'bid':
            # For bids, sum all volume at better prices (higher than ours)
            total_ahead = Decimal('0')
            if obm.use_rust:
                # For Rust implementation, we only have best bid/ask
                best_bid = obm.l2_book.best_bid
                if best_bid and Decimal(str(best_bid[0])) > target_price:
                    total_ahead += Decimal(str(best_bid[1]))
            else:
                # Python fallback - sum all bids with price > target_price
                for bid_price, bid_size in obm.bids.items():
                    if bid_price > target_price:
                        total_ahead += bid_size
                        
        elif side.lower() == 'ask':
            # For asks, sum all volume at better prices (lower than ours)
            total_ahead = Decimal('0')
            if obm.use_rust:
                # For Rust implementation, we only have best bid/ask
                best_ask = obm.l2_book.best_ask
                if best_ask and Decimal(str(best_ask[0])) < target_price:
                    total_ahead += Decimal(str(best_ask[1]))
            else:
                # Python fallback - sum all asks with price < target_price
                for ask_price, ask_size in obm.asks.items():
                    if ask_price < target_price:
                        total_ahead += ask_size
        
        return float(total_ahead)
    
    def topN_volumes(self, symbol: str, N: int = 5) -> Tuple[float, float]:
        """
        Get total volume for top N levels on both sides.
        
        Args:
            symbol: Trading symbol
            N: Number of levels to aggregate
            
        Returns:
            Tuple of (bid_volume, ask_volume)
        """
        if symbol not in self.orderbooks:
            return (0.0, 0.0)
            
        obm = self.orderbooks[symbol]
        
        if obm.use_rust:
            # For Rust implementation, we only have best bid/ask
            bid_vol = 0.0
            ask_vol = 0.0
            if N >= 1:
                best_bid = obm.l2_book.best_bid
                best_ask = obm.l2_book.best_ask
                if best_bid:
                    bid_vol = best_bid[1]
                if best_ask:
                    ask_vol = best_ask[1]
            return (bid_vol, ask_vol)
        else:
            # Python fallback - get top N levels
            # Sort bids descending and take top N
            sorted_bids = sorted(obm.bids.items(), key=lambda x: x[0], reverse=True)[:N]
            bid_volume = sum(float(size) for _, size in sorted_bids)
            
            # Sort asks ascending and take top N  
            sorted_asks = sorted(obm.asks.items(), key=lambda x: x[0])[:N]
            ask_volume = sum(float(size) for _, size in sorted_asks)
            
            return (bid_volume, ask_volume)
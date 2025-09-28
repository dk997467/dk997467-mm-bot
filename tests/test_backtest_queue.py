"""
Tests for backtest queue simulation functionality.

Tests:
- Queue-based fill simulation
- Deterministic synthetic order book
- Fill generation and statistics
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import Mock

from src.backtest.queue_sim import QueueSimulator, SimulatedOrder, SimulatedFill
from src.marketdata.orderbook import OrderBookAggregator
from src.common.models import OrderBook, PriceLevel, Side


class TestBacktestQueue:
    """Test backtest queue simulation."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create mock orderbook aggregator
        self.mock_orderbook_aggregator = Mock(spec=OrderBookAggregator)
        self.mock_orderbook_aggregator.ahead_volume.return_value = 1.0
        
        # Create queue simulator
        self.queue_simulator = QueueSimulator(self.mock_orderbook_aggregator)
        
        # Create test symbol
        self.symbol = "BTCUSDT"
    
    def test_initialization(self):
        """Test queue simulator initialization."""
        assert len(self.queue_simulator.active_orders) == 0
        assert len(self.queue_simulator.fills) == 0
        assert self.queue_simulator.total_fills == 0
        assert self.queue_simulator.maker_fills == 0
        assert self.queue_simulator.taker_fills == 0
    
    def test_add_order(self):
        """Test adding orders to the simulation."""
        # Create test orders
        order1 = SimulatedOrder(
            order_id="order1",
            symbol=self.symbol,
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("0.001"),
            timestamp=datetime.now(timezone.utc)
        )
        
        order2 = SimulatedOrder(
            order_id="order2",
            symbol=self.symbol,
            side=Side.SELL,
            price=Decimal("50001"),
            qty=Decimal("0.001"),
            timestamp=datetime.now(timezone.utc)
        )
        
        # Add orders
        assert self.queue_simulator.add_order(order1)
        assert self.queue_simulator.add_order(order2)
        
        # Check that orders were added
        assert self.symbol in self.queue_simulator.active_orders
        assert len(self.queue_simulator.active_orders[self.symbol]['Buy']) == 1
        assert len(self.queue_simulator.active_orders[self.symbol]['Sell']) == 1
        
        # Check order sorting (bids should be sorted by price descending)
        bid_orders = self.queue_simulator.active_orders[self.symbol]['Buy']
        assert bid_orders[0].price == Decimal("50000")
        
        # Check order sorting (asks should be sorted by price ascending)
        ask_orders = self.queue_simulator.active_orders[self.symbol]['Sell']
        assert ask_orders[0].price == Decimal("50001")
    
    def test_cancel_order(self):
        """Test canceling orders from the simulation."""
        # Add an order
        order = SimulatedOrder(
            order_id="order1",
            symbol=self.symbol,
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("0.001"),
            timestamp=datetime.now(timezone.utc)
        )
        
        self.queue_simulator.add_order(order)
        assert len(self.queue_simulator.active_orders[self.symbol]['Buy']) == 1
        
        # Cancel the order
        assert self.queue_simulator.cancel_order(self.symbol, "order1")
        assert len(self.queue_simulator.active_orders[self.symbol]['Buy']) == 0
        
        # Try to cancel non-existent order
        assert not self.queue_simulator.cancel_order(self.symbol, "nonexistent")
    
    def test_bid_fill_simulation(self):
        """Test bid fill simulation when ask price drops."""
        # Add a bid order
        bid_order = SimulatedOrder(
            order_id="bid1",
            symbol=self.symbol,
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("0.001"),
            timestamp=datetime.now(timezone.utc)
        )
        
        self.queue_simulator.add_order(bid_order)
        
        # Create orderbook with ask price below our bid
        orderbook = OrderBook(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            bids=[PriceLevel(price=Decimal("49999"), size=Decimal("1.0"), sequence=1)],
            asks=[PriceLevel(price=Decimal("49998"), size=Decimal("1.0"), sequence=1)]
        )
        
        # Mock ahead volume for ask side
        self.mock_orderbook_aggregator.ahead_volume.return_value = 0.001
        
        # Simulate market moves
        fills = self.queue_simulator.simulate_market_moves(orderbook)
        
        # Check that we got a fill
        assert len(fills) == 1
        fill = fills[0]
        
        assert fill.order_id == "bid1"
        assert fill.symbol == self.symbol
        assert fill.side == Side.BUY
        assert fill.fill_price == Decimal("49998")  # We get filled at ask price
        assert fill.fill_qty == Decimal("0.001")
        assert fill.is_maker == True
        
        # Check that order was updated
        assert bid_order.filled_qty == Decimal("0.001")
        assert not bid_order.is_active
        
        # Check statistics
        assert self.queue_simulator.total_fills == 1
        assert self.queue_simulator.maker_fills == 1
        assert self.queue_simulator.taker_fills == 0
    
    def test_ask_fill_simulation(self):
        """Test ask fill simulation when bid price rises."""
        # Add an ask order
        ask_order = SimulatedOrder(
            order_id="ask1",
            symbol=self.symbol,
            side=Side.SELL,
            price=Decimal("50001"),
            qty=Decimal("0.001"),
            timestamp=datetime.now(timezone.utc)
        )
        
        self.queue_simulator.add_order(ask_order)
        
        # Create orderbook with bid price above our ask
        orderbook = OrderBook(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            bids=[PriceLevel(price=Decimal("50002"), size=Decimal("1.0"), sequence=1)],
            asks=[PriceLevel(price=Decimal("50003"), size=Decimal("1.0"), sequence=1)]
        )
        
        # Mock ahead volume for bid side
        self.mock_orderbook_aggregator.ahead_volume.return_value = 0.001
        
        # Simulate market moves
        fills = self.queue_simulator.simulate_market_moves(orderbook)
        
        # Check that we got a fill
        assert len(fills) == 1
        fill = fills[0]
        
        assert fill.order_id == "ask1"
        assert fill.symbol == self.symbol
        assert fill.side == Side.SELL
        assert fill.fill_price == Decimal("50002")  # We get filled at bid price
        assert fill.fill_qty == Decimal("0.001")
        assert fill.is_maker == True
        
        # Check that order was updated
        assert ask_order.filled_qty == Decimal("0.001")
        assert not ask_order.is_active
        
        # Check statistics
        assert self.queue_simulator.total_fills == 1
        assert self.queue_simulator.maker_fills == 1
        assert self.queue_simulator.taker_fills == 0
    
    def test_partial_fill(self):
        """Test partial fill when available volume is less than order quantity."""
        # Add a bid order with large quantity
        bid_order = SimulatedOrder(
            order_id="bid1",
            symbol=self.symbol,
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("0.002"),
            timestamp=datetime.now(timezone.utc)
        )
        
        self.queue_simulator.add_order(bid_order)
        
        # Create orderbook with limited ask volume
        orderbook = OrderBook(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            bids=[PriceLevel(price=Decimal("49999"), size=Decimal("1.0"), sequence=1)],
            asks=[PriceLevel(price=Decimal("49998"), size=Decimal("1.0"), sequence=1)]
        )
        
        # Mock limited ahead volume
        self.mock_orderbook_aggregator.ahead_volume.return_value = 0.001
        
        # Simulate market moves
        fills = self.queue_simulator.simulate_market_moves(orderbook)
        
        # Check that we got a partial fill
        assert len(fills) == 1
        fill = fills[0]
        
        assert fill.fill_qty == Decimal("0.001")  # Limited by available volume
        
        # Check that order was partially filled but still active
        assert bid_order.filled_qty == Decimal("0.001")
        assert bid_order.is_active  # Still has remaining quantity
        assert bid_order.remaining_qty == Decimal("0.001")
    
    def test_no_fill_scenario(self):
        """Test scenario where no fills occur."""
        # Add orders that won't be filled
        bid_order = SimulatedOrder(
            order_id="bid1",
            symbol=self.symbol,
            side=Side.BUY,
            price=Decimal("49900"),  # Much lower than market
            qty=Decimal("0.001"),
            timestamp=datetime.now(timezone.utc)
        )
        
        ask_order = SimulatedOrder(
            order_id="ask1",
            symbol=self.symbol,
            side=Side.SELL,
            price=Decimal("50100"),  # Much higher than market
            qty=Decimal("0.001"),
            timestamp=datetime.now(timezone.utc)
        )
        
        self.queue_simulator.add_order(bid_order)
        self.queue_simulator.add_order(ask_order)
        
        # Create orderbook with prices that won't trigger fills
        orderbook = OrderBook(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            bids=[PriceLevel(price=Decimal("50000"), size=Decimal("1.0"), sequence=1)],
            asks=[PriceLevel(price=Decimal("50001"), size=Decimal("1.0"), sequence=1)]
        )
        
        # Simulate market moves
        fills = self.queue_simulator.simulate_market_moves(orderbook)
        
        # Check that no fills occurred
        assert len(fills) == 0
        
        # Check that orders are still active
        assert bid_order.is_active
        assert ask_order.is_active
        assert bid_order.filled_qty == Decimal("0")
        assert ask_order.filled_qty == Decimal("0")
    
    def test_queue_position_calculation(self):
        """Test queue position calculation."""
        # Add multiple orders at different price levels
        orders = [
            SimulatedOrder("bid1", self.symbol, Side.BUY, Decimal("50002"), Decimal("0.001"), datetime.now(timezone.utc)),
            SimulatedOrder("bid2", self.symbol, Side.BUY, Decimal("50001"), Decimal("0.001"), datetime.now(timezone.utc)),
            SimulatedOrder("bid3", self.symbol, Side.BUY, Decimal("50000"), Decimal("0.001"), datetime.now(timezone.utc)),
        ]
        
        for order in orders:
            self.queue_simulator.add_order(order)
        
        # Check queue positions
        assert self.queue_simulator.get_queue_position(self.symbol, "Buy", Decimal("50002")) == 0  # Best price
        assert self.queue_simulator.get_queue_position(self.symbol, "Buy", Decimal("50001")) == 1  # Second best
        assert self.queue_simulator.get_queue_position(self.symbol, "Buy", Decimal("50000")) == 2  # Third best
        
        # Test ask side
        ask_orders = [
            SimulatedOrder("ask1", self.symbol, Side.SELL, Decimal("50003"), Decimal("0.001"), datetime.now(timezone.utc)),
            SimulatedOrder("ask2", self.symbol, Side.SELL, Decimal("50004"), Decimal("0.001"), datetime.now(timezone.utc)),
        ]
        
        for order in ask_orders:
            self.queue_simulator.add_order(order)
        
        assert self.queue_simulator.get_queue_position(self.symbol, "Sell", Decimal("50003")) == 0  # Best price
        assert self.queue_simulator.get_queue_position(self.symbol, "Sell", Decimal("50004")) == 1  # Second best
    
    def test_active_orders_summary(self):
        """Test active orders summary generation."""
        # Add some orders
        orders = [
            SimulatedOrder("bid1", self.symbol, Side.BUY, Decimal("50000"), Decimal("0.001"), datetime.now(timezone.utc)),
            SimulatedOrder("bid2", self.symbol, Side.BUY, Decimal("49999"), Decimal("0.002"), datetime.now(timezone.utc)),
            SimulatedOrder("ask1", self.symbol, Side.SELL, Decimal("50001"), Decimal("0.001"), datetime.now(timezone.utc)),
        ]
        
        for order in orders:
            self.queue_simulator.add_order(order)
        
        # Get summary
        summary = self.queue_simulator.get_active_orders_summary(self.symbol)
        
        assert summary['symbol'] == self.symbol
        assert summary['total_orders'] == 3
        
        # Check bid side
        bid_summary = summary['orders_by_side']['Buy']
        assert bid_summary['count'] == 2
        assert bid_summary['total_qty'] == 0.003  # 0.001 + 0.002
        
        # Check ask side
        ask_summary = summary['orders_by_side']['Sell']
        assert ask_summary['count'] == 1
        assert ask_summary['total_qty'] == 0.001
    
    def test_fill_statistics(self):
        """Test fill statistics generation."""
        # Add and fill some orders
        bid_order = SimulatedOrder(
            order_id="bid1",
            symbol=self.symbol,
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("0.001"),
            timestamp=datetime.now(timezone.utc)
        )
        
        self.queue_simulator.add_order(bid_order)
        
        # Create orderbook that will trigger fill
        orderbook = OrderBook(
            symbol=self.symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            bids=[PriceLevel(price=Decimal("49999"), size=Decimal("1.0"), sequence=1)],
            asks=[PriceLevel(price=Decimal("49998"), size=Decimal("1.0"), sequence=1)]
        )
        
        self.mock_orderbook_aggregator.ahead_volume.return_value = 0.001
        
        # Simulate market moves
        self.queue_simulator.simulate_market_moves(orderbook)
        
        # Get statistics
        stats = self.queue_simulator.get_fill_statistics()
        
        assert stats['total_fills'] == 1
        assert stats['maker_fills'] == 1
        assert stats['taker_fills'] == 0
        assert stats['maker_ratio'] == 1.0
        assert stats['total_fill_value'] == 49.998  # 0.001 * 49998
    
    def test_reset_functionality(self):
        """Test reset functionality."""
        # Add some orders and fills
        order = SimulatedOrder(
            order_id="test1",
            symbol=self.symbol,
            side=Side.BUY,
            price=Decimal("50000"),
            qty=Decimal("0.001"),
            timestamp=datetime.now(timezone.utc)
        )
        
        self.queue_simulator.add_order(order)
        
        # Verify data exists
        assert self.symbol in self.queue_simulator.active_orders
        assert len(self.queue_simulator.active_orders[self.symbol]['Buy']) == 1
        
        # Reset symbol
        self.queue_simulator.reset_symbol(self.symbol)
        
        # Verify data is removed
        assert self.symbol not in self.queue_simulator.active_orders
        
        # Test reset all
        self.queue_simulator.add_order(order)
        self.queue_simulator.reset_all()
        
        assert len(self.queue_simulator.active_orders) == 0
        assert len(self.queue_simulator.fills) == 0
        assert self.queue_simulator.total_fills == 0

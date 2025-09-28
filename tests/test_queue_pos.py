"""
Test queue position tracking and metrics with new OrderManager API.

Tests:
- Queue position delta metrics are updated correctly
- ahead_volume simulation works
- Metrics reflect queue position changes
"""

import asyncio
import pytest
import time
from unittest.mock import Mock

from prometheus_client import REGISTRY

from src.common.config import AppConfig, StrategyConfig, LimitsConfig, TradingConfig
from src.common.di import AppContext
from src.execution.order_manager import OrderManager
from src.metrics.exporter import Metrics
from tests.conftest import FakeREST, FakeOrderBook


class TestQueuePosition:
    """Test queue position tracking and metrics."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear Prometheus registry to avoid duplicate metric errors
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        
        # Create config
        self.config = AppConfig(
            strategy=StrategyConfig(
                levels_per_side=2,
                min_time_in_book_ms=200,
                replace_threshold_bps=3
            ),
            limits=LimitsConfig(
                max_active_per_side=5,
                max_create_per_sec=10,
                max_cancel_per_sec=10
            ),
            trading=TradingConfig(
                symbols=["BTCUSDT"],
                max_active_orders_per_side=10
            )
        )
        
        # Create AppContext with metrics
        self.ctx = AppContext(cfg=self.config)
        self.ctx.metrics = Metrics(self.ctx)
        
        # Create mocks
        self.rest_connector = FakeREST(latency_ms=1)
        self.orderbook = FakeOrderBook()
        
        # Create OrderManager
        self.order_manager = OrderManager(self.ctx, self.rest_connector)
    
    async def test_queue_position_metrics_initialization(self):
        """Test that queue position metrics are initialized correctly."""
        symbol = "BTCUSDT"
        side = "Buy"
        
        # Check initial metric values
        queue_pos = self.ctx.metrics.queue_pos_delta.labels(symbol=symbol, side=side)._value.get()
        assert queue_pos == 0.0
    
    async def test_queue_position_tracking_with_ahead_volume(self):
        """Test queue position tracking with ahead_volume simulation."""
        symbol = "BTCUSDT"
        side = "Buy"
        price = 50000.0
        qty = 0.001
        
        # Set up orderbook with ahead volume
        self.orderbook.set_ahead_volume(symbol, side, price, 100.0)
        
        # Place order at this price level
        cid = await self.order_manager.place_order(
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=qty,
            price=price
        )
        
        # Simulate trade consumption
        self.orderbook.consume(symbol, side, 50.0)
        
        # Update queue position metric (this would normally be done by strategy)
        # For testing, we'll manually simulate the queue position calculation
        ahead_volume = self.orderbook.ahead_volume(symbol, side, price)
        queue_pos_delta = 100.0 - ahead_volume  # Positive = improved position
        
        self.ctx.metrics.update_queue_pos_delta(symbol, side, queue_pos_delta)
        
        # Check that metric was updated
        updated_queue_pos = self.ctx.metrics.queue_pos_delta.labels(symbol=symbol, side=side)._value.get()
        assert updated_queue_pos == 50.0
        
        # Clean up
        await self.order_manager.cancel_order(cid)
    
    async def test_queue_position_improvement_simulation(self):
        """Test queue position improvement over multiple steps."""
        symbol = "BTCUSDT"
        side = "Buy"
        price = 50000.0
        qty = 0.001
        
        # Set up orderbook with high ahead volume
        self.orderbook.set_ahead_volume(symbol, side, price, 200.0)
        
        # Place order
        cid = await self.order_manager.place_order(
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=qty,
            price=price
        )
        
        # Simulate progressive trade consumption
        consumption_steps = [50.0, 30.0, 20.0, 10.0]
        expected_queue_positions = [50.0, 80.0, 100.0, 110.0]  # Cumulative consumption
        
        for i, consumption in enumerate(consumption_steps):
            # Consume volume
            self.orderbook.consume(symbol, side, consumption)
            
            # Calculate new queue position (cumulative consumption)
            ahead_volume = self.orderbook.ahead_volume(symbol, side, price)
            queue_pos_delta = 200.0 - ahead_volume
            
            # Update metric
            self.ctx.metrics.update_queue_pos_delta(symbol, side, queue_pos_delta)
            
            # Check metric value
            current_queue_pos = self.ctx.metrics.queue_pos_delta.labels(symbol=symbol, side=side)._value.get()
            assert current_queue_pos == expected_queue_positions[i]
        
        # Clean up
        await self.order_manager.cancel_order(cid)
    
    async def test_queue_position_both_sides(self):
        """Test queue position tracking for both buy and sell sides."""
        symbol = "BTCUSDT"
        buy_price = 50000.0
        sell_price = 50001.0
        qty = 0.001
        
        # Set up orderbook for both sides
        self.orderbook.set_ahead_volume(symbol, "Buy", buy_price, 100.0)
        self.orderbook.set_ahead_volume(symbol, "Sell", sell_price, 80.0)
        
        # Place orders on both sides
        buy_cid = await self.order_manager.place_order(
            symbol=symbol,
            side="Buy",
            order_type="Limit",
            qty=qty,
            price=buy_price
        )
        
        sell_cid = await self.order_manager.place_order(
            symbol=symbol,
            side="Sell",
            order_type="Limit",
            qty=qty,
            price=sell_price
        )
        
        # Simulate consumption on both sides
        self.orderbook.consume(symbol, "Buy", 30.0)
        self.orderbook.consume(symbol, "Sell", 20.0)
        
        # Update queue position metrics
        buy_ahead = self.orderbook.ahead_volume(symbol, "Buy", buy_price)
        sell_ahead = self.orderbook.ahead_volume(symbol, "Sell", sell_price)
        
        buy_queue_pos = 100.0 - buy_ahead
        sell_queue_pos = 80.0 - sell_ahead
        
        self.ctx.metrics.update_queue_pos_delta(symbol, "Buy", buy_queue_pos)
        self.ctx.metrics.update_queue_pos_delta(symbol, "Sell", sell_queue_pos)
        
        # Check both metrics
        buy_metric = self.ctx.metrics.queue_pos_delta.labels(symbol=symbol, side="Buy")._value.get()
        sell_metric = self.ctx.metrics.queue_pos_delta.labels(symbol=symbol, side="Sell")._value.get()
        
        assert buy_metric == 30.0
        assert sell_metric == 20.0
        
        # Clean up
        await self.order_manager.cancel_order(buy_cid)
        await self.order_manager.cancel_order(sell_cid)
    
    async def test_queue_position_metric_persistence(self):
        """Test that queue position metrics persist across operations."""
        symbol = "BTCUSDT"
        side = "Buy"
        price = 50000.0
        qty = 0.001
        
        # Set initial queue position
        initial_queue_pos = 25.0
        self.ctx.metrics.update_queue_pos_delta(symbol, side, initial_queue_pos)
        
        # Verify initial value
        queue_pos = self.ctx.metrics.queue_pos_delta.labels(symbol=symbol, side=side)._value.get()
        assert queue_pos == initial_queue_pos
        
        # Place and cancel an order (should not affect queue position metric)
        cid = await self.order_manager.place_order(
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=qty,
            price=price
        )
        
        await self.order_manager.cancel_order(cid)
        
        # Queue position metric should remain unchanged
        queue_pos_after = self.ctx.metrics.queue_pos_delta.labels(symbol=symbol, side=side)._value.get()
        assert queue_pos_after == initial_queue_pos
    
    async def test_queue_position_metric_labels(self):
        """Test that queue position metrics have correct labels."""
        symbol = "BTCUSDT"
        side = "Buy"
        
        # Check that metric has correct labels
        metric = self.ctx.metrics.queue_pos_delta
        assert 'symbol' in metric._labelnames
        assert 'side' in metric._labelnames
        
        # Check that we can access the metric with labels
        labeled_metric = metric.labels(symbol=symbol, side=side)
        assert labeled_metric is not None
        
        # Set and get value
        test_value = 42.0
        labeled_metric.set(test_value)
        retrieved_value = labeled_metric._value.get()
        assert retrieved_value == test_value

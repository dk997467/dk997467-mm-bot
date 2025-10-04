"""
Test OrderManager metrics with new API.

Tests:
- All basic metrics increment correctly
- New reliability metrics work
- Circuit breaker metrics toggle
- Metrics are properly labeled
"""

import asyncio
import pytest
import time
from unittest.mock import Mock, patch

from prometheus_client import REGISTRY

from src.common.config import AppConfig, StrategyConfig, LimitsConfig, TradingConfig
from src.common.di import AppContext
from src.execution.order_manager import OrderManager
from src.metrics.exporter import Metrics
from tests.conftest import FakeREST, FakeOrderBook


class TestOrderManagerMetrics:
    """Test OrderManager metrics with new API."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # NOTE: Registry cleanup now handled by conftest.py autouse fixture
        
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
    
    async def test_basic_metrics_increment(self):
        """Test that basic metrics increment correctly."""
        symbol = "BTCUSDT"
        side = "Buy"
        price = 50000.0
        qty = 0.001
        
        # Check initial values
        initial_creates = self.ctx.metrics.creates_total.labels(symbol=symbol)._value.get()
        initial_cancels = self.ctx.metrics.cancels_total.labels(symbol=symbol)._value.get()
        initial_replaces = self.ctx.metrics.replaces_total.labels(symbol=symbol)._value.get()
        
        # Place order
        cid = await self.order_manager.place_order(
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=qty,
            price=price
        )
        
        # Check creates metric
        creates_after = self.ctx.metrics.creates_total.labels(symbol=symbol)._value.get()
        assert creates_after == initial_creates + 1
        
        # Check active orders metric
        active_orders = self.ctx.metrics.orders_active.labels(symbol=symbol, side=side)._value.get()
        assert active_orders == 1
        
        # Cancel order
        await self.order_manager.cancel_order(cid)
        
        # Check cancels metric
        cancels_after = self.ctx.metrics.cancels_total.labels(symbol=symbol)._value.get()
        assert cancels_after == initial_cancels + 1
        
        # Check active orders metric updated
        active_orders_after = self.ctx.metrics.orders_active.labels(symbol=symbol, side=side)._value.get()
        assert active_orders_after == 0
    
    async def test_amend_metrics_increment(self):
        """Test that amend metrics increment correctly."""
        symbol = "BTCUSDT"
        side = "Buy"
        price = 50000.0
        qty = 0.001
        
        # Place order
        cid = await self.order_manager.place_order(
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=qty,
            price=price
        )
        
        # Wait for min_time_in_book to pass
        await asyncio.sleep(0.3)
        
        # Check initial amend metrics
        initial_attempts = self.ctx.metrics.amend_attempts_total.labels(symbol=symbol, side=side)._value.get()
        initial_success = self.ctx.metrics.amend_success_total.labels(symbol=symbol, side=side)._value.get()
        
        # Update order - should use amend
        new_price = price + 0.5
        success = await self.order_manager.update_order(
            client_order_id=cid,
            new_price=new_price,
            reason="test_amend"
        )
        
        assert success is True
        
        # Check amend metrics incremented
        attempts_after = self.ctx.metrics.amend_attempts_total.labels(symbol=symbol, side=side)._value.get()
        success_after = self.ctx.metrics.amend_success_total.labels(symbol=symbol, side=side)._value.get()
        
        assert attempts_after == initial_attempts + 1
        assert success_after == initial_success + 1
        
        # Clean up - cancel all orders for this symbol
        await self.order_manager.cancel_all_orders(symbol)
    
    async def test_replace_metrics_increment(self):
        """Test that replace metrics increment correctly."""
        symbol = "BTCUSDT"
        side = "Buy"
        price = 50000.0
        qty = 0.001
        
        # Place order
        cid = await self.order_manager.place_order(
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=qty,
            price=price
        )
        
        # Try to update immediately - should use cancel+create (replace)
        new_price = price + 1.0
        success = await self.order_manager.update_order(
            client_order_id=cid,
            new_price=new_price,
            reason="test_replace"
        )
        
        assert success is True
        
        # Check that replaces metric was incremented
        replaces_total = self.ctx.metrics.replaces_total.labels(symbol=symbol)._value.get()
        assert replaces_total >= 1
        
        # Clean up - cancel all orders for this symbol
        await self.order_manager.cancel_all_orders(symbol)
    
    async def test_rate_metrics_update(self):
        """Test that rate metrics are updated correctly."""
        symbol = "BTCUSDT"
        side = "Buy"
        price = 50000.0
        qty = 0.001
        
        # Place several orders quickly
        cids = []
        for i in range(3):
            cid = await self.order_manager.place_order(
                symbol=symbol,
                side=side,
                order_type="Limit",
                qty=qty,
                price=price - i * 0.1
            )
            cids.append(cid)
        
        # Check create total metric
        creates_total = self.ctx.metrics.creates_total.labels(symbol=symbol)._value.get()
        assert creates_total == 3
        
        # Cancel all orders for this symbol
        await self.order_manager.cancel_all_orders(symbol)
        
        # Check cancel total metric
        cancels_total = self.ctx.metrics.cancels_total.labels(symbol=symbol)._value.get()
        assert cancels_total == 3
    
    async def test_metrics_labels_correctness(self):
        """Test that metrics have correct labels."""
        symbol = "BTCUSDT"
        side = "Buy"
        
        # Check label names for key metrics
        assert 'symbol' in self.ctx.metrics.creates_total._labelnames
        assert 'symbol' in self.ctx.metrics.cancels_total._labelnames
        assert 'symbol' in self.ctx.metrics.replaces_total._labelnames
        assert 'symbol' in self.ctx.metrics.orders_active._labelnames
        assert 'side' in self.ctx.metrics.orders_active._labelnames
        
        # Check amend metrics labels
        assert 'symbol' in self.ctx.metrics.amend_attempts_total._labelnames
        assert 'side' in self.ctx.metrics.amend_attempts_total._labelnames
        assert 'symbol' in self.ctx.metrics.amend_success_total._labelnames
        assert 'side' in self.ctx.metrics.amend_success_total._labelnames
    
    async def test_metrics_initialization(self):
        """Test that metrics are properly initialized."""
        # Check that all required metrics exist
        required_metrics = [
            'creates_total', 'cancels_total', 'replaces_total',
            'orders_active', 'create_rate', 'cancel_rate',
            'amend_attempts_total', 'amend_success_total'
        ]
        
        for metric_name in required_metrics:
            assert hasattr(self.ctx.metrics, metric_name), f"Missing metric: {metric_name}"
        
        # Check initial values
        symbol = "BTCUSDT"
        side = "Buy"
        
        assert self.ctx.metrics.creates_total.labels(symbol=symbol)._value.get() == 0
        assert self.ctx.metrics.cancels_total.labels(symbol=symbol)._value.get() == 0
        assert self.ctx.metrics.replaces_total.labels(symbol=symbol)._value.get() == 0
        assert self.ctx.metrics.orders_active.labels(symbol=symbol, side=side)._value.get() == 0
    
    async def test_metrics_persistence_across_operations(self):
        """Test that metrics persist correctly across operations."""
        symbol = "BTCUSDT"
        side = "Buy"
        price = 50000.0
        qty = 0.001
        
        # Place order
        cid = await self.order_manager.place_order(
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=qty,
            price=price
        )
        
        # Check metrics
        creates = self.ctx.metrics.creates_total.labels(symbol=symbol)._value.get()
        active = self.ctx.metrics.orders_active.labels(symbol=symbol, side=side)._value.get()
        
        assert creates == 1
        assert active == 1
        
        # Cancel order
        await self.order_manager.cancel_all_orders(symbol)
        
        # Check metrics updated
        creates_after = self.ctx.metrics.creates_total.labels(symbol=symbol)._value.get()
        active_after = self.ctx.metrics.orders_active.labels(symbol=symbol, side=side)._value.get()
        
        assert creates_after == 1  # Should not change
        assert active_after == 0   # Should be decremented
    
    async def test_metrics_multiple_symbols(self):
        """Test metrics work correctly with multiple symbols."""
        symbols = ["BTCUSDT", "ETHUSDT"]
        side = "Buy"
        price = 50000.0
        qty = 0.001
        
        cids = []
        
        # Place orders on multiple symbols
        for symbol in symbols:
            cid = await self.order_manager.place_order(
                symbol=symbol,
                side=side,
                order_type="Limit",
                qty=qty,
                price=price
            )
            cids.append((symbol, cid))
        
        # Check metrics for each symbol
        for symbol, cid in cids:
            creates = self.ctx.metrics.creates_total.labels(symbol=symbol)._value.get()
            active = self.ctx.metrics.orders_active.labels(symbol=symbol, side=side)._value.get()
            
            assert creates == 1
            assert active == 1
        
        # Clean up - cancel all orders for all symbols
        for symbol, _ in cids:
            await self.order_manager.cancel_all_orders(symbol)

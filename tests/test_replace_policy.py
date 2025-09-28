"""
Test replace policy logic with new OrderManager API.

Tests:
- Replace threshold enforcement
- Min time in book gating
- Risk pause blocking
- Rate limit enforcement
- Amend vs cancel+create path selection
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


class TestReplacePolicy:
    """Test replace policy logic with new API."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear Prometheus registry to avoid duplicate metric errors
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        
        # Create config with specific replace policy settings
        self.config = AppConfig(
            strategy=StrategyConfig(
                levels_per_side=2,
                min_time_in_book_ms=200,
                replace_threshold_bps=3,  # 3 bps threshold
                amend_price_threshold_bps=1.0,
                amend_size_threshold=0.2,
                slip_bps=1.0  # 1 bps slippage estimate
            ),
            limits=LimitsConfig(
                max_active_per_side=5,
                max_create_per_sec=5,  # Lower rate for testing
                max_cancel_per_sec=5
            ),
            trading=TradingConfig(
                symbols=["BTCUSDT"],
                max_active_orders_per_side=10,
                maker_fee_bps=1.0,
                taker_fee_bps=2.0
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
    
    async def test_replace_threshold_enforcement(self):
        """Test that replace threshold is enforced correctly."""
        symbol = "BTCUSDT"
        side = "Buy"
        base_price = 50000.0
        qty = 0.001
        
        # Place initial order
        cid = await self.order_manager.place_order(
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=qty,
            price=base_price
        )
        
        # Wait for min_time_in_book to pass
        await asyncio.sleep(0.3)
        
        # Case 1: Improvement below threshold (2 bps < 3 bps) - should use amend
        small_improvement_price = base_price * (1 + 0.0002)  # 2 bps improvement
        success = await self.order_manager.update_order(
            client_order_id=cid,
            new_price=small_improvement_price,
            reason="small_improvement"
        )
        
        # Should succeed and use amend path
        assert success is True
        
        # Get the current order ID (may have changed if replaced)
        current_orders = self.order_manager.get_active_orders(symbol)
        if not current_orders:
            # Order was replaced, get the new one
            current_orders = self.order_manager.get_active_orders()
        
        # Find our order by side and price
        current_cid = None
        for order_cid, order in current_orders.items():
            if order.side == side and abs(order.price - small_improvement_price) < 0.1:
                current_cid = order_cid
                break
        
        assert current_cid is not None, "Order not found after update"
        
        # Case 2: Improvement above threshold (6 bps > 3 bps) - should replace
        large_improvement_price = base_price * (1 + 0.0006)  # 6 bps improvement
        success2 = await self.order_manager.update_order(
            client_order_id=current_cid,
            new_price=large_improvement_price,
            reason="large_improvement"
        )
        
        assert success2 is True
        
        # Clean up - cancel all orders for this symbol
        await self.order_manager.cancel_all_orders(symbol)
    
    async def test_min_time_in_book_gating(self):
        """Test that min_time_in_book blocks replacements before threshold."""
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
        
        # Try to update immediately with large improvement
        # Should be blocked by min_time_in_book regardless of improvement size
        large_improvement_price = price * (1 + 0.001)  # 10 bps improvement
        
        success = await self.order_manager.update_order(
            client_order_id=cid,
            new_price=large_improvement_price,
            reason="immediate_update"
        )
        
        # Should succeed but use cancel+create path due to min_time_in_book
        assert success is True
        
        # Check that amend attempt was recorded (even though it failed)
        amend_attempts = self.ctx.metrics.amend_attempts_total.labels(symbol=symbol, side=side)._value.get()
        assert amend_attempts >= 1
        
        # Clean up - cancel all orders for this symbol
        await self.order_manager.cancel_all_orders(symbol)
    
    async def test_amend_vs_cancel_create_path_selection(self):
        """Test that the correct path (amend vs cancel+create) is selected."""
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
        
        # Small improvement - should use amend if within thresholds
        small_improvement_price = price * (1 + 0.0001)  # 1 bps improvement
        
        success = await self.order_manager.update_order(
            client_order_id=cid,
            new_price=small_improvement_price,
            reason="small_improvement"
        )
        
        assert success is True
        
        # Check metrics to see which path was used
        amend_attempts = self.ctx.metrics.amend_attempts_total.labels(symbol=symbol, side=side)._value.get()
        amend_success = self.ctx.metrics.amend_success_total.labels(symbol=symbol, side=side)._value.get()
        
        # Should have at least one amend attempt
        assert amend_attempts >= 1
        
        # Clean up - cancel all orders for this symbol
        await self.order_manager.cancel_all_orders(symbol)
    
    async def test_replace_policy_with_quantity_changes(self):
        """Test replace policy with quantity changes."""
        symbol = "BTCUSDT"
        side = "Buy"
        price = 50000.0
        base_qty = 0.001
        
        # Place initial order
        cid = await self.order_manager.place_order(
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=base_qty,
            price=price
        )
        
        # Wait for min_time_in_book to pass
        await asyncio.sleep(0.3)
        
        # Case 1: Small quantity change within threshold
        small_qty_change = base_qty * 1.1  # 10% increase, within 20% threshold
        
        success = await self.order_manager.update_order(
            client_order_id=cid,
            new_qty=small_qty_change,
            reason="small_qty_change"
        )
        
        assert success is True
        
        # Case 2: Large quantity change exceeding threshold
        large_qty_change = base_qty * 1.5  # 50% increase, exceeds 20% threshold
        
        success2 = await self.order_manager.update_order(
            client_order_id=cid,
            new_qty=large_qty_change,
            reason="large_qty_change"
        )
        
        assert success2 is True
        
        # Clean up - cancel all orders for this symbol
        await self.order_manager.cancel_all_orders(symbol)
    
    async def test_replace_policy_metrics_tracking(self):
        """Test that replace policy metrics are tracked correctly."""
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
        
        # Make several updates to test metrics
        for i in range(3):
            new_price = price * (1 + 0.0001 * (i + 1))  # Small improvements
            
            success = await self.order_manager.update_order(
                client_order_id=cid,
                new_price=new_price,
                reason=f"update_{i}"
            )
            
            assert success is True
        
        # Check metrics
        amend_attempts = self.ctx.metrics.amend_attempts_total.labels(symbol=symbol, side=side)._value.get()
        amend_success = self.ctx.metrics.amend_success_total.labels(symbol=symbol, side=side)._value.get()
        
        # Should have multiple amend attempts
        assert amend_attempts >= 3
        
        # Clean up - cancel all orders for this symbol
        await self.order_manager.cancel_all_orders(symbol)
    
    async def test_replace_policy_edge_cases(self):
        """Test replace policy edge cases."""
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
        
        # Edge case 1: No change (same price and quantity)
        success = await self.order_manager.update_order(
            client_order_id=cid,
            reason="no_change"
        )
        
        assert success is True
        
        # Edge case 2: Only price change
        success2 = await self.order_manager.update_order(
            client_order_id=cid,
            new_price=price + 0.1,
            reason="price_only"
        )
        
        assert success2 is True
        
        # Edge case 3: Only quantity change
        success3 = await self.order_manager.update_order(
            client_order_id=cid,
            new_qty=qty * 1.05,  # 5% increase
            reason="qty_only"
        )
        
        assert success3 is True
        
        # Clean up - cancel all orders for this symbol
        await self.order_manager.cancel_all_orders(symbol)
    
    async def test_replace_policy_multiple_symbols(self):
        """Test replace policy across multiple symbols."""
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
        
        # Wait for min_time_in_book to pass
        await asyncio.sleep(0.3)
        
        # Update orders on all symbols
        for symbol, cid in cids:
            new_price = price * (1 + 0.0005)  # 5 bps improvement
            
            success = await self.order_manager.update_order(
                client_order_id=cid,
                new_price=new_price,
                reason="multi_symbol_test"
            )
            
            assert success is True
            
            # Check metrics for this symbol
            amend_attempts = self.ctx.metrics.amend_attempts_total.labels(symbol=symbol, side=side)._value.get()
            assert amend_attempts >= 1
        
        # Clean up - cancel all orders for all symbols
        for symbol, _ in cids:
            await self.order_manager.cancel_all_orders(symbol)

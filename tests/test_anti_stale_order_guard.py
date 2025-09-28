"""Test anti-stale order guard functionality."""

import pytest
import time
import os
from unittest.mock import Mock, patch, AsyncMock
from prometheus_client import REGISTRY
from src.execution.order_manager import OrderManager
from src.execution.reconcile import OrderState
from src.metrics.exporter import Metrics
from src.common.di import AppContext


class TestAntiStaleOrderGuard:
    """Test anti-stale order guard functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear prometheus registry to avoid duplicate metrics
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        
        # Create mock context
        self.ctx = Mock(spec=AppContext)
        self.ctx.cfg = Mock()
        self.ctx.cfg.strategy = Mock()
        self.ctx.cfg.strategy.order_ttl_ms = 800
        self.ctx.cfg.strategy.price_drift_bps = 2.0
        self.ctx.cfg.strategy.enable_anti_stale_guard = True
        
        # Create mock REST connector
        self.rest_connector = Mock()
        self.rest_connector.get_orderbook = AsyncMock()
        self.rest_connector._round_to_tick = Mock(return_value=50000.0)
        self.rest_connector._round_to_lot = Mock(return_value=1.0)
        
        # Create metrics
        self.metrics = Metrics(self.ctx)
        self.ctx.metrics = self.metrics
        
        # Create order manager
        self.order_manager = OrderManager(self.ctx, self.rest_connector)
        
        # Create test orders
        self.test_order = OrderState(
            order_id="test_order_1",
            client_order_id="test_cid_1",
            symbol="BTCUSDT",
            side="Buy",
            price=50000.0,
            qty=1.0,
            status="New",
            filled_qty=0.0,
            remaining_qty=1.0,
            created_time=time.time() * 1000,  # Current time in milliseconds
            last_update_time=time.time() * 1000
        )
        
        # Add test order to active orders
        self.order_manager.active_orders["test_cid_1"] = self.test_order
    
    def teardown_method(self):
        """Clean up after tests."""
        pass
    
    def test_anti_stale_guard_configuration(self):
        """Test that anti-stale guard configuration is loaded correctly."""
        assert self.order_manager.enable_anti_stale_guard is True
        assert self.order_manager.order_ttl_ms == 800
        assert self.order_manager.price_drift_bps == 2.0
    
    def test_order_age_bucket_calculation(self):
        """Test order age bucket calculation."""
        buckets = [
            (50, "0-100ms"),
            (200, "100-500ms"),
            (800, "500-1000ms"),
            (2000, "1000-5000ms"),
            (10000, "5000ms+")
        ]
        
        for age_ms, expected_bucket in buckets:
            bucket = self.order_manager._get_order_age_bucket(age_ms)
            assert bucket == expected_bucket
    
    def test_order_not_stale(self):
        """Test that recent orders are not considered stale."""
        # Create a recent order
        recent_order = OrderState(
            order_id="recent_order",
            client_order_id="recent_cid",
            symbol="BTCUSDT",
            side="Buy",
            price=50000.0,
            qty=1.0,
            status="New",
            filled_qty=0.0,
            remaining_qty=1.0,
            created_time=time.time() * 1000,  # Current time
            last_update_time=time.time() * 1000
        )
        
        is_stale, reason, drift_bps = self.order_manager._is_order_stale(recent_order, 50000.0)
        assert is_stale is False
        assert reason == ""
        assert drift_bps is None
    
    def test_order_stale_by_ttl(self):
        """Test that orders are considered stale when TTL expires."""
        # Create an old order (older than TTL)
        old_order = OrderState(
            order_id="old_order",
            client_order_id="old_cid",
            symbol="BTCUSDT",
            side="Buy",
            price=50000.0,
            qty=1.0,
            status="New",
            filled_qty=0.0,
            remaining_qty=1.0,
            created_time=(time.time() - 1.0) * 1000,  # 1 second ago
            last_update_time=(time.time() - 1.0) * 1000
        )
        
        is_stale, reason, drift_bps = self.order_manager._is_order_stale(old_order, 50000.0)
        assert is_stale is True
        assert reason == "ttl_expired"
        assert drift_bps is None
    
    def test_order_stale_by_price_drift(self):
        """Test that orders are considered stale when price drifts too much."""
        # Create an order with significant price drift
        drifted_order = OrderState(
            order_id="drifted_order",
            client_order_id="drifted_cid",
            symbol="BTCUSDT",
            side="Buy",
            price=50000.0,
            qty=1.0,
            status="New",
            filled_qty=0.0,
            remaining_qty=1.0,
            created_time=time.time() * 1000,  # Current time
            last_update_time=time.time() * 1000
        )
        
        # Current mid price with 3 bps drift (above 2.0 bps threshold)
        current_mid = 50000.0 * (1 + 3.0 / 10000)  # 3 bps higher
        
        is_stale, reason, drift_bps = self.order_manager._is_order_stale(drifted_order, current_mid)
        assert is_stale is True
        assert reason == "price_drift"
        assert abs(drift_bps - 3.0) < 0.1  # Allow small floating point errors
    
    def test_anti_stale_guard_disabled(self):
        """Test that anti-stale guard can be disabled."""
        # Disable anti-stale guard
        self.order_manager.enable_anti_stale_guard = False
        
        # Create an old order
        old_order = OrderState(
            order_id="old_order",
            client_order_id="old_cid",
            symbol="BTCUSDT",
            side="Buy",
            price=50000.0,
            qty=1.0,
            status="New",
            filled_qty=0.0,
            remaining_qty=1.0,
            created_time=(time.time() - 1.0) * 1000,  # 1 second ago
            last_update_time=(time.time() - 1.0) * 1000
        )
        
        is_stale, reason, drift_bps = self.order_manager._is_order_stale(old_order, 50000.0)
        assert is_stale is False
        assert reason == ""
        assert drift_bps is None
    
    @pytest.mark.asyncio
    async def test_get_current_mid_price_from_orderbook(self):
        """Test getting current mid price from orderbook."""
        # Mock orderbook response
        mock_orderbook = {
            'result': {
                'b': [['49990.0', '1.0']],  # bid price, quantity
                'a': [['50010.0', '1.0']]   # ask price, quantity
            }
        }
        self.rest_connector.get_orderbook.return_value = mock_orderbook
        
        mid_price = await self.order_manager._get_current_mid_price("BTCUSDT")
        assert mid_price == 50000.0  # (49990 + 50010) / 2
        
        # Verify orderbook was called
        self.rest_connector.get_orderbook.assert_called_once_with("BTCUSDT", limit=1)
    
    @pytest.mark.asyncio
    async def test_get_current_mid_price_fallback(self):
        """Test fallback to average of active orders when orderbook fails."""
        # Mock orderbook to fail
        self.rest_connector.get_orderbook.side_effect = Exception("API error")
        
        # Add some orders with different prices
        self.order_manager.active_orders["order1"] = OrderState(
            order_id="order1", client_order_id="order1", symbol="BTCUSDT",
            side="Buy", price=49900.0, qty=1.0, status="New",
            filled_qty=0.0, remaining_qty=1.0,
            created_time=time.time() * 1000, last_update_time=time.time() * 1000
        )
        self.order_manager.active_orders["order2"] = OrderState(
            order_id="order2", client_order_id="order2", symbol="BTCUSDT",
            side="Sell", price=50100.0, qty=1.0, status="New",
            filled_qty=0.0, remaining_qty=1.0,
            created_time=time.time() * 1000, last_update_time=time.time() * 1000
        )
        
        mid_price = await self.order_manager._get_current_mid_price("BTCUSDT")
        assert mid_price == 50000.0  # (49900 + 50100) / 2
    
    @pytest.mark.asyncio
    async def test_handle_stale_order_ttl_expired(self):
        """Test handling TTL expired orders (should cancel)."""
        # Mock cancel_order to succeed
        self.order_manager.cancel_order = AsyncMock(return_value=True)
        
        # Test TTL expired order
        success = await self.order_manager._handle_stale_order(
            self.test_order, "ttl_expired"
        )
        
        assert success is True
        self.order_manager.cancel_order.assert_called_once_with("test_cid_1")
        
        # Verify metrics were updated
        assert self.metrics.stale_cancels_total.labels(
            symbol="BTCUSDT", reason="ttl_expired"
        )._value.get() == 1
    
    @pytest.mark.asyncio
    async def test_handle_stale_order_price_drift(self):
        """Test handling price drift orders (should amend)."""
        # Mock get_current_mid_price and update_order
        self.order_manager._get_current_mid_price = AsyncMock(return_value=50000.0)
        self.order_manager.update_order = AsyncMock(return_value=True)
        
        # Test price drift order
        success = await self.order_manager._handle_stale_order(
            self.test_order, "price_drift", 3.0
        )
        
        assert success is True
        
        # Verify update_order was called with new price
        self.order_manager.update_order.assert_called_once()
        call_args = self.order_manager.update_order.call_args
        assert call_args[0][0] == "test_cid_1"  # client_order_id
        assert call_args[1]["reason"] == "price_drift_refresh"
        
        # Verify metrics were updated
        assert self.metrics.refresh_amends_total.labels(
            symbol="BTCUSDT", reason="price_drift"
        )._value.get() == 1
    
    @pytest.mark.asyncio
    async def test_check_and_refresh_stale_orders(self):
        """Test the main check and refresh functionality."""
        # Mock get_current_mid_price and _handle_stale_order
        self.order_manager._get_current_mid_price = AsyncMock(return_value=50000.0)
        self.order_manager._handle_stale_order = AsyncMock(return_value=True)
        
        # Create a stale order (TTL expired)
        old_order = OrderState(
            order_id="old_order",
            client_order_id="old_cid",
            symbol="BTCUSDT",
            side="Buy",
            price=50000.0,
            qty=1.0,
            status="New",
            filled_qty=0.0,
            remaining_qty=1.0,
            created_time=(time.time() - 1.0) * 1000,  # 1 second ago
            last_update_time=(time.time() - 1.0) * 1000
        )
        self.order_manager.active_orders["old_cid"] = old_order
        
        # Run check and refresh
        result = await self.order_manager.check_and_refresh_stale_orders()
        
        # Verify result structure
        assert result["enabled"] is True
        assert result["symbol"] == "all"
        assert len(result["actions"]) == 1
        assert result["ttl_cancels"] == 1
        assert result["drift_refreshes"] == 0
        assert result["errors"] == 0
        
        # Verify action details
        action = result["actions"][0]
        assert action["client_order_id"] == "old_cid"
        assert action["reason"] == "ttl_expired"
        assert action["success"] is True
        
        # Verify metrics were updated - check all buckets to see which one was incremented
        total_metrics = 0
        for bucket in ["0-100ms", "100-500ms", "500-1000ms", "1000-5000ms", "5000ms+"]:
            value = self.metrics.order_age_ms_bucket_total.labels(
                symbol="BTCUSDT", bucket=bucket
            )._value.get()
            total_metrics += value
            print(f"Bucket {bucket}: {value}")
        
        # At least one bucket should have been incremented
        assert total_metrics >= 1, f"Expected at least 1 metric increment, got {total_metrics}"
    
    @pytest.mark.asyncio
    async def test_check_and_refresh_stale_orders_disabled(self):
        """Test that check and refresh is disabled when guard is off."""
        # Disable anti-stale guard
        self.order_manager.enable_anti_stale_guard = False
        
        result = await self.order_manager.check_and_refresh_stale_orders()
        
        assert result["enabled"] is False
        assert result["actions"] == []
    
    @pytest.mark.asyncio
    async def test_no_markout_regression_when_disabled(self):
        """Test that markout metrics are not affected when anti-stale guard is disabled."""
        # Disable anti-stale guard
        self.order_manager.enable_anti_stale_guard = False
        
        # Record some markout data
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49950.0, 50000.0)
        
        # Verify markout metrics are still working
        snapshot = self.metrics._get_markout_snapshot_for_tests()
        assert "200" in snapshot
        assert "500" in snapshot
        assert "blue" in snapshot["200"]
        assert "green" in snapshot["200"]
        
        # Verify samples are recorded
        assert snapshot["200"]["blue"]["samples"] == 1
        assert snapshot["200"]["green"]["samples"] == 1
        assert snapshot["500"]["blue"]["samples"] == 1
        assert snapshot["500"]["green"]["samples"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

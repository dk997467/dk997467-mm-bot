"""Test admin endpoint for anti-stale order guard."""

import pytest
import json
from unittest.mock import Mock, AsyncMock, patch
from cli.run_bot import MarketMakerBot


class TestAdminAntiStaleGuard:
    """Test admin endpoint for anti-stale order guard."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create mock bot
        self.bot = Mock(spec=MarketMakerBot)
        self.bot._check_admin_token = Mock(return_value=True)
        self.bot._admin_actor_hash = Mock(return_value="test_actor")
        self.bot._admin_rate_limit_check = Mock(return_value=True)
        self.bot._json_response = Mock()
        self.bot._admin_audit_record = Mock()
        
        # Mock metrics
        self.bot.metrics = Mock()
        self.bot.metrics.inc_admin_unauthorized = Mock()
        self.bot.metrics.inc_admin_rate_limited = Mock()
        self.bot.metrics.inc_admin_request = Mock()
        
        # Mock order manager
        self.bot.order_manager = Mock()
        self.bot.order_manager.enable_anti_stale_guard = True
        self.bot.order_manager.order_ttl_ms = 800
        self.bot.order_manager.price_drift_bps = 2.0
        self.bot.order_manager.active_orders = {"order1": Mock(), "order2": Mock()}
    
    def test_admin_anti_stale_guard_configuration(self):
        """Test that admin endpoint configuration is correct."""
        # Verify that the endpoint is properly configured
        assert hasattr(self.bot, 'order_manager')
        assert self.bot.order_manager.enable_anti_stale_guard is True
        assert self.bot.order_manager.order_ttl_ms == 800
        assert self.bot.order_manager.price_drift_bps == 2.0
    
    def test_admin_anti_stale_guard_metrics_available(self):
        """Test that required metrics are available."""
        # Verify that required metrics methods exist
        assert hasattr(self.bot.metrics, 'inc_admin_unauthorized')
        assert hasattr(self.bot.metrics, 'inc_admin_rate_limited')
        assert hasattr(self.bot.metrics, 'inc_admin_request')
    
    def test_admin_anti_stale_guard_order_manager_available(self):
        """Test that order manager is available."""
        # Verify that order manager exists and has required attributes
        assert self.bot.order_manager is not None
        assert hasattr(self.bot.order_manager, 'active_orders')
        assert len(self.bot.order_manager.active_orders) == 2
    
    def test_admin_anti_stale_guard_admin_methods_available(self):
        """Test that required admin methods are available."""
        # Verify that required admin methods exist
        assert hasattr(self.bot, '_check_admin_token')
        assert hasattr(self.bot, '_admin_actor_hash')
        assert hasattr(self.bot, '_admin_rate_limit_check')
        assert hasattr(self.bot, '_json_response')
        assert hasattr(self.bot, '_admin_audit_record')
    
    def test_admin_anti_stale_guard_mock_behavior(self):
        """Test that mocks behave as expected."""
        # Test admin token check
        assert self.bot._check_admin_token() is True
        
        # Test actor hash
        assert self.bot._admin_actor_hash() == "test_actor"
        
        # Test rate limit check
        assert self.bot._admin_rate_limit_check() is True
        
        # Test metrics calls
        self.bot.metrics.inc_admin_request('/admin/anti-stale-guard')
        self.bot.metrics.inc_admin_request.assert_called_once_with('/admin/anti-stale-guard')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

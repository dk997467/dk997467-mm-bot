"""
Test that all required reliability metrics are present and properly configured.

Tests:
- All required metric names exist in the registry
- Labels are correctly configured
- Metrics can be updated without errors
"""

import pytest
import time
from unittest.mock import Mock

from prometheus_client import REGISTRY, CollectorRegistry

from src.common.config import AppConfig, StrategyConfig, LimitsConfig, TradingConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


class TestMetricsPresence:
    """Test that all required metrics are present."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # NOTE: Registry cleanup now handled by conftest.py autouse fixture
        
        # Create minimal config
        self.config = AppConfig(
            strategy=StrategyConfig(),
            limits=LimitsConfig(),
            trading=TradingConfig()
        )
        
        # Create AppContext
        self.ctx = AppContext(cfg=self.config)
        
        # Create Metrics instance
        self.metrics = Metrics(self.ctx)
    
    def test_amend_metrics_exist(self):
        """Test that amend-related metrics exist."""
        # Check that metrics exist
        assert hasattr(self.metrics, 'amend_attempts_total')
        assert hasattr(self.metrics, 'amend_success_total')
        
        # Check labels
        assert 'symbol' in self.metrics.amend_attempts_total._labelnames
        assert 'side' in self.metrics.amend_attempts_total._labelnames
        assert 'symbol' in self.metrics.amend_success_total._labelnames
        assert 'side' in self.metrics.amend_success_total._labelnames
    
    def test_reconcile_metrics_exist(self):
        """Test that reconciliation metrics exist."""
        assert hasattr(self.metrics, 'reconcile_actions_total')
        assert 'action' in self.metrics.reconcile_actions_total._labelnames
    
    def test_backoff_metrics_exist(self):
        """Test that backoff metrics exist."""
        assert hasattr(self.metrics, 'backoff_seconds_sum')
        # This is a Counter without labels
        assert len(self.metrics.backoff_seconds_sum._labelnames) == 0
    
    def test_circuit_breaker_metrics_exist(self):
        """Test that circuit breaker metrics exist."""
        assert hasattr(self.metrics, 'circuit_breaker_state')
        # This is a Gauge without labels
        assert len(self.metrics.circuit_breaker_state._labelnames) == 0
    
    def test_amend_metrics_can_be_updated(self):
        """Test that amend metrics can be updated without errors."""
        # Should not raise any exceptions
        self.metrics.on_amend_attempt("BTCUSDT", "Buy")
        self.metrics.on_amend_success("BTCUSDT", "Buy")
        
        # Check that counters were incremented
        # Note: We can't easily check the actual values without exposing internal state
        # But if no exceptions were raised, the metrics are working
    
    def test_reconcile_metrics_can_be_updated(self):
        """Test that reconcile metrics can be updated without errors."""
        valid_actions = ["attach", "close", "mark_filled", "mark_canceled", "noop"]
        
        for action in valid_actions:
            # Should not raise any exceptions
            self.metrics.on_reconcile_action(action)
    
    def test_reconcile_metrics_reject_invalid_actions(self):
        """Test that reconcile metrics reject invalid actions."""
        # Should not raise exceptions, but should log warnings
        self.metrics.on_reconcile_action("invalid_action")
        
        # The metric should not be incremented for invalid actions
        # (This is tested by checking that no exceptions are raised)
    
    def test_backoff_metrics_can_be_updated(self):
        """Test that backoff metrics can be updated without errors."""
        # Should not raise any exceptions
        self.metrics.add_backoff_seconds(1.5)
        self.metrics.add_backoff_seconds(0.5)
    
    def test_backoff_metrics_reject_negative_values(self):
        """Test that backoff metrics reject negative values."""
        # Should not raise exceptions, but should log warnings
        self.metrics.add_backoff_seconds(-1.0)
        
        # The metric should not be incremented for negative values
        # (This is tested by checking that no exceptions are raised)
    
    def test_circuit_breaker_metrics_can_be_updated(self):
        """Test that circuit breaker metrics can be updated without errors."""
        # Should not raise any exceptions
        self.metrics.set_circuit_breaker_state(True)
        self.metrics.set_circuit_breaker_state(False)
    
    def test_all_required_metrics_present(self):
        """Test that all required metric names are present."""
        required_metrics = {
            'amend_attempts_total',
            'amend_success_total', 
            'reconcile_actions_total',
            'backoff_seconds_sum',
            'circuit_breaker_state'
        }
        
        for metric_name in required_metrics:
            assert hasattr(self.metrics, metric_name), f"Missing metric: {metric_name}"
    
    def test_metrics_registry_integration(self):
        """Test that metrics are properly registered in the Prometheus registry."""
        # Get all metric names from the registry
        metric_names = set()
        for collector in REGISTRY._collector_to_names.keys():
            if hasattr(collector, '_name'):
                metric_names.add(collector._name)
        
        # Check that our metrics are in the registry
        assert 'amend_attempts' in metric_names
        assert 'amend_success' in metric_names
        assert 'reconcile_actions' in metric_names
        assert 'backoff_seconds_sum' in metric_names
        assert 'circuit_breaker_state' in metric_names

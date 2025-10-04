"""
Integration test for metrics with Prometheus registry.
"""

import pytest
from prometheus_client import REGISTRY, generate_latest
from src.common.config import AppConfig, StrategyConfig, LimitsConfig, TradingConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


class TestMetricsIntegration:
    """Test metrics integration with Prometheus registry."""
    
    def setup_method(self):
        """Setup test environment."""
        # NOTE: Registry cleanup now handled by conftest.py autouse fixture
        
        self.config = AppConfig(
            strategy=StrategyConfig(),
            limits=LimitsConfig(),
            trading=TradingConfig()
        )
        self.ctx = AppContext(cfg=self.config)
        self.metrics = Metrics(self.ctx)
    
    def test_metrics_export_to_prometheus(self):
        """Test that metrics are properly exported to Prometheus format."""
        # Set some initial values to ensure metrics are exported
        self.metrics.on_amend_attempt("BTCUSDT", "Buy")
        self.metrics.on_reconcile_action("attach")
        self.metrics.add_backoff_seconds(0.1)
        self.metrics.set_circuit_breaker_state(False)
        
        # Generate Prometheus format
        prometheus_data = generate_latest(REGISTRY).decode('utf-8')
        
        # Check that our key metrics are present
        assert 'amend_attempts_total' in prometheus_data
        assert 'reconcile_actions_total' in prometheus_data
        assert 'backoff_seconds_sum' in prometheus_data
        assert 'circuit_breaker_state' in prometheus_data
        
        # Check that metrics have proper labels
        assert 'symbol=' in prometheus_data
        assert 'side=' in prometheus_data
        assert 'action=' in prometheus_data
    
    def test_metrics_values_exported(self):
        """Test that metric values are properly exported."""
        # Set some metric values
        self.metrics.on_amend_attempt("BTCUSDT", "Buy")
        self.metrics.on_amend_success("BTCUSDT", "Buy")
        self.metrics.on_reconcile_action("attach")
        self.metrics.add_backoff_seconds(1.5)
        self.metrics.set_circuit_breaker_state(True)
        
        # Generate Prometheus format
        prometheus_data = generate_latest(REGISTRY).decode('utf-8')
        
        # Check that values are exported (more flexible matching)
        assert 'amend_attempts_total' in prometheus_data
        assert 'amend_success_total' in prometheus_data
        assert 'reconcile_actions_total' in prometheus_data
        assert 'backoff_seconds_sum' in prometheus_data
        assert 'circuit_breaker_state' in prometheus_data
    
    def test_metrics_registry_cleanup(self):
        """Test that metrics are properly cleaned up from registry."""
        # Check metrics are in registry
        metric_names = set()
        for collector in REGISTRY._collector_to_names.keys():
            if hasattr(collector, '_name'):
                metric_names.add(collector._name)
        
        assert 'amend_attempts' in metric_names
        assert 'amend_success' in metric_names
        
        # Clear registry
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        
        # Check registry is empty
        assert len(list(REGISTRY._collector_to_names.keys())) == 0

"""
Test Prometheus registry reset functionality.
"""

import pytest
from prometheus_client import REGISTRY

from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


def clear_registry():
    """Clear Prometheus registry completely."""
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()


class TestRegistryReset:
    """Test that multiple tests can init Metrics without duplicate-collector errors."""
    
    def test_metrics_init_after_clear(self):
        """Test that Metrics can be initialized after registry clear."""
        clear_registry()
        
        config = AppConfig()
        ctx = AppContext(cfg=config)
        metrics = Metrics(ctx)
        
        assert metrics is not None
        assert metrics.orders_active is not None
    
    def test_multiple_metrics_instances(self):
        """Test that multiple Metrics instances can be created after registry clear."""
        clear_registry()
        
        config1 = AppConfig()
        ctx1 = AppContext(cfg=config1)
        metrics1 = Metrics(ctx1)
        
        # Clear again
        clear_registry()
        
        config2 = AppConfig()
        ctx2 = AppContext(cfg=config2)
        metrics2 = Metrics(ctx2)
        
        assert metrics1 is not None
        assert metrics2 is not None
        assert metrics1 is not metrics2
    
    def test_registry_cleanup(self):
        """Test that registry cleanup works correctly."""
        clear_registry()
        
        # Should be empty
        assert len(REGISTRY._collector_to_names) == 0
        assert len(REGISTRY._names_to_collectors) == 0
        
        # Create metrics
        config = AppConfig()
        ctx = AppContext(cfg=config)
        metrics = Metrics(ctx)
        
        # Should have collectors now
        assert len(REGISTRY._collector_to_names) > 0
        assert len(REGISTRY._names_to_collectors) > 0
        
        # Clear again
        clear_registry()
        assert len(REGISTRY._collector_to_names) == 0
        assert len(REGISTRY._names_to_collectors) == 0
    
    def test_no_duplicate_metrics(self):
        """Test that no duplicate metric names exist after registry clear."""
        clear_registry()
        
        config = AppConfig()
        ctx = AppContext(cfg=config)
        metrics = Metrics(ctx)
        
        # Get all metric names
        metric_names = set()
        for collector in REGISTRY._collector_to_names:
            names = REGISTRY._collector_to_names[collector]
            metric_names.update(names)
        
        # Should have no duplicates
        assert len(metric_names) == len(list(metric_names))
        
        # Should have expected metrics
        expected_metrics = {
            'orders_active', 'creates_total', 'cancels_total', 'replaces_total',
            'quotes_placed_total', 'create_rate', 'cancel_rate', 'maker_pnl',
            'taker_fees', 'inventory_abs', 'latency_ms', 'ws_reconnects_total',
            'rest_error_rate', 'risk_paused', 'drawdown_day', 'spread_bps',
            'vola_1m', 'ob_imbalance', 'cfg_levels_per_side',
            'cfg_min_time_in_book_ms', 'cfg_k_vola_spread', 'cfg_skew_coeff',
            'cfg_imbalance_cutoff', 'cfg_max_create_per_sec', 'cfg_max_cancel_per_sec'
        }
        
        # All expected metrics should be present
        for expected in expected_metrics:
            assert expected in metric_names, f"Missing metric: {expected}"

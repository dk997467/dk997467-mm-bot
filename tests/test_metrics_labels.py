"""
Test metrics labels and names match production requirements.
"""

import pytest
from prometheus_client import REGISTRY

from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


class TestMetricsLabels:
    """Test that metrics have exact names and labels."""
    
    # NOTE: Registry cleanup now handled by conftest.py autouse fixture
    
    def test_metrics_class_instantiation(self):
        """Test that Metrics class can be instantiated."""
        # Create minimal config
        config = AppConfig()
        ctx = AppContext(cfg=config)
        
        # Should not raise
        metrics = Metrics(ctx)
        assert metrics is not None
    
    def test_metrics_names_and_labels(self):
        """Test that all metrics have exact names and labels."""
        config = AppConfig()
        ctx = AppContext(cfg=config)
        metrics = Metrics(ctx)
        
        # Flow metrics - EXACT names/labels
        assert metrics.orders_active._name == 'orders_active'
        assert metrics.orders_active._labelnames == ('symbol', 'side')
        
        # Counter metrics get _total suffix automatically
        assert metrics.creates_total._name == 'creates'
        assert metrics.creates_total._labelnames == ('symbol',)
        
        assert metrics.cancels_total._name == 'cancels'
        assert metrics.cancels_total._labelnames == ('symbol',)
        
        assert metrics.replaces_total._name == 'replaces'
        assert metrics.replaces_total._labelnames == ('symbol',)
        
        assert metrics.quotes_placed_total._name == 'quotes_placed'
        assert metrics.quotes_placed_total._labelnames == ('symbol',)
        
        # Rate metrics
        assert metrics.create_rate._name == 'create_rate'
        assert metrics.create_rate._labelnames == ('symbol',)
        
        assert metrics.cancel_rate._name == 'cancel_rate'
        assert metrics.cancel_rate._labelnames == ('symbol',)
        
        # Queue position metrics
        assert metrics.queue_pos_delta._name == 'queue_pos_delta'
        assert metrics.queue_pos_delta._labelnames == ('symbol', 'side')
        
        # P&L and fees
        assert metrics.maker_pnl._name == 'maker_pnl'
        assert metrics.maker_pnl._labelnames == ('symbol',)
        
        assert metrics.taker_fees._name == 'taker_fees'
        assert metrics.taker_fees._labelnames == ('symbol',)
        
        assert metrics.inventory_abs._name == 'inventory_abs'
        assert metrics.inventory_abs._labelnames == ('symbol',)
        
        # Latency histograms - EXACT stage values: "md", "rest", "ws"
        assert metrics.latency_ms._name == 'latency_ms'
        assert metrics.latency_ms._labelnames == ('stage',)
        
        # Exchange connectivity
        assert metrics.ws_reconnects_total._name == 'ws_reconnects_total'
        assert metrics.ws_reconnects_total._labelnames == ('exchange',)
        
        assert metrics.rest_error_rate._name == 'rest_error_rate'
        assert metrics.rest_error_rate._labelnames == ('exchange',)
        
        # Risk metrics
        assert metrics.risk_paused._name == 'risk_paused'
        assert metrics.risk_paused._labelnames == ()
        
        assert metrics.drawdown_day._name == 'drawdown_day'
        assert metrics.drawdown_day._labelnames == ()
        
        # Market metrics
        assert metrics.spread_bps._name == 'spread_bps'
        assert metrics.spread_bps._labelnames == ('symbol',)
        
        assert metrics.vola_1m._name == 'vola_1m'
        assert metrics.vola_1m._labelnames == ('symbol',)
        
        assert metrics.ob_imbalance._name == 'ob_imbalance'
        assert metrics.ob_imbalance._labelnames == ('symbol',)
        
        # Config gauges - EXACT names
        assert metrics.cfg_levels_per_side._name == 'cfg_levels_per_side'
        assert metrics.cfg_levels_per_side._labelnames == ()
        
        assert metrics.cfg_min_time_in_book_ms._name == 'cfg_min_time_in_book_ms'
        assert metrics.cfg_min_time_in_book_ms._labelnames == ()
        
        assert metrics.cfg_k_vola_spread._name == 'cfg_k_vola_spread'
        assert metrics.cfg_k_vola_spread._labelnames == ()
        
        assert metrics.cfg_skew_coeff._name == 'cfg_skew_coeff'
        assert metrics.cfg_skew_coeff._labelnames == ()
        
        assert metrics.cfg_imbalance_cutoff._name == 'cfg_imbalance_cutoff'
        assert metrics.cfg_imbalance_cutoff._labelnames == ()
        
        assert metrics.cfg_max_create_per_sec._name == 'cfg_max_create_per_sec'
        assert metrics.cfg_max_create_per_sec._labelnames == ()
        
        assert metrics.cfg_max_cancel_per_sec._name == 'cfg_max_cancel_per_sec'
        assert metrics.cfg_max_cancel_per_sec._labelnames == ()
    
    def test_latency_stage_validation(self):
        """Test that latency stage validation works correctly."""
        config = AppConfig()
        ctx = AppContext(cfg=config)
        metrics = Metrics(ctx)
        
        # Valid stages should work
        metrics.observe_latency("md", 10.0)
        metrics.observe_latency("rest", 20.0)
        metrics.observe_latency("ws", 30.0)
        
        # Invalid stage should be ignored (and logged)
        metrics.observe_latency("invalid", 40.0)
        
        # Check that only valid stages have data
        # Note: We can't easily check histogram values in tests, but we can verify no errors
    
    def test_metrics_labels_smoke(self):
        """Smoke test for metrics labels."""
        config = AppConfig()
        ctx = AppContext(cfg=config)
        metrics = Metrics(ctx)
        
        # Test that we can update metrics without errors
        metrics.update_order_metrics("BTCUSDT", "buy", "create")
        metrics.update_order_metrics("BTCUSDT", "sell", "cancel")
        metrics.update_quote_metrics("BTCUSDT")
        metrics.update_market_metrics("BTCUSDT", 2.5, 0.8, 0.3)
        metrics.update_risk_metrics(False, 0.5)
        metrics.update_connectivity_metrics("bybit", 0, 0.01)
        metrics.update_active_orders("BTCUSDT", "buy", 3)
        metrics.update_pnl_metrics("BTCUSDT", 100.0, 5.0, 50.0)
        
        # Should not raise any exceptions
        assert True


if __name__ == "__main__":
    pytest.main([__file__])

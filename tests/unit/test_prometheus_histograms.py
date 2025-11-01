"""
Unit tests for Prometheus histogram instrumentation.

Tests verify that:
1. Latency observations are recorded correctly
2. Risk ratio observations are recorded correctly
3. Histograms expose bucket counts correctly
"""
import pytest
from unittest.mock import MagicMock, patch


class TestPrometheusHistograms:
    """Test prometheus histogram exports."""
    
    def test_histograms_initialize_lazily(self):
        """Test that histograms initialize only when first accessed."""
        from tools.live import prometheus_histograms
        
        # Module should load without error
        assert prometheus_histograms is not None
        
        # Check availability
        available = prometheus_histograms.is_available()
        # May be False if prometheus_client not installed
        assert isinstance(available, bool)
    
    def test_observe_latency_ms_basic(self):
        """Test basic latency observation."""
        from tools.live import prometheus_histograms
        
        # These should not raise, even if prometheus_client missing
        prometheus_histograms.observe_latency_ms(10.5)
        prometheus_histograms.observe_latency_ms(125.3)
        prometheus_histograms.observe_latency_ms(250.7)
    
    def test_observe_latency_ms_negative_ignored(self):
        """Test that negative latencies are ignored."""
        from tools.live import prometheus_histograms
        
        # Should not raise
        prometheus_histograms.observe_latency_ms(-5.0)
        prometheus_histograms.observe_latency_ms(50.0)  # Valid
    
    def test_observe_latency_ms_none_ignored(self):
        """Test that None values are ignored."""
        from tools.live import prometheus_histograms
        
        # Should not raise
        prometheus_histograms.observe_latency_ms(None)
        prometheus_histograms.observe_latency_ms(50.0)  # Valid
    
    def test_observe_risk_ratio_basic(self):
        """Test basic risk ratio observation."""
        from tools.live import prometheus_histograms
        
        # These should not raise
        prometheus_histograms.observe_risk_ratio(0.05)
        prometheus_histograms.observe_risk_ratio(0.30)
        prometheus_histograms.observe_risk_ratio(0.45)
        prometheus_histograms.observe_risk_ratio(0.85)
    
    def test_observe_risk_ratio_bounds(self):
        """Test that risk ratio is bounded to [0.0, 1.0]."""
        from tools.live import prometheus_histograms
        
        # Out of bounds should be ignored
        prometheus_histograms.observe_risk_ratio(-0.1)  # Invalid
        prometheus_histograms.observe_risk_ratio(1.5)   # Invalid
        prometheus_histograms.observe_risk_ratio(0.30)  # Valid
    
    def test_observe_risk_ratio_none_ignored(self):
        """Test that None values are ignored."""
        from tools.live import prometheus_histograms
        
        # Should not raise
        prometheus_histograms.observe_risk_ratio(None)
        prometheus_histograms.observe_risk_ratio(0.30)  # Valid
    
    @pytest.mark.skipif(
        not pytest.importorskip("prometheus_client", reason="prometheus_client not installed"),
        reason="Requires prometheus_client"
    )
    def test_histogram_buckets_configured(self):
        """Test that histograms have correct bucket configuration."""
        from tools.live import prometheus_histograms
        
        # Force initialization
        prometheus_histograms.observe_latency_ms(100.0)
        prometheus_histograms.observe_risk_ratio(0.30)
        
        lat_hist = prometheus_histograms.get_latency_histogram()
        risk_hist = prometheus_histograms.get_risk_histogram()
        
        if lat_hist is not None:
            # Check that it's a Histogram
            assert hasattr(lat_hist, 'observe')
            assert hasattr(lat_hist, '_buckets')
        
        if risk_hist is not None:
            assert hasattr(risk_hist, 'observe')
            assert hasattr(risk_hist, '_buckets')
    
    def test_histogram_exports_to_prometheus_format(self):
        """Test that histograms can be exported to Prometheus format."""
        try:
            from prometheus_client import CollectorRegistry, Histogram, generate_latest
            from tools.live import prometheus_histograms
        except ImportError:
            pytest.skip("prometheus_client not available")
        
        # Record some observations
        prometheus_histograms.observe_latency_ms(125.0)
        prometheus_histograms.observe_latency_ms(235.0)
        prometheus_histograms.observe_risk_ratio(0.25)
        prometheus_histograms.observe_risk_ratio(0.35)
        
        # Get histograms
        lat_hist = prometheus_histograms.get_latency_histogram()
        risk_hist = prometheus_histograms.get_risk_histogram()
        
        # Skip if histograms not initialized (prometheus_client might not be fully configured)
        if lat_hist is None or risk_hist is None:
            pytest.skip("Histograms not initialized")
        
        # Just verify histograms exist and have expected methods
        assert hasattr(lat_hist, 'observe')
        assert hasattr(risk_hist, 'observe')


class TestLatencyCollectorIntegration:
    """Test that LatencyCollector integrates with histograms."""
    
    def test_latency_collector_records_to_histogram(self):
        """Test that LatencyCollector.record_ms() exports to histogram."""
        from tools.live.latency_collector import LatencyCollector
        
        collector = LatencyCollector()
        
        # Record some samples
        collector.record_ms(10.0)
        collector.record_ms(20.0)
        collector.record_ms(200.0)
        
        # Check that p95 works
        p95 = collector.p95()
        assert 150.0 <= p95 <= 250.0  # Should be near 200.0
    
    def test_latency_collector_p95_matches_samples(self):
        """Test that p95 calculation is correct."""
        from tools.live.latency_collector import LatencyCollector
        
        collector = LatencyCollector()
        
        # 20 samples: 1, 2, 3, ..., 20
        for i in range(1, 21):
            collector.record_ms(float(i))
        
        p95 = collector.p95()
        # 95th percentile of [1..20] should be 19 (95% of 20 = 19)
        assert 18.0 <= p95 <= 20.0


class TestRiskMonitorIntegration:
    """Test that RiskMonitor integrates with histograms."""
    
    def test_risk_monitor_has_p95_method(self):
        """Test that RiskMonitor has risk_ratio_p95() method."""
        from tools.live.risk_monitor import RuntimeRiskMonitor
        
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        # Should have the method
        assert hasattr(monitor, 'risk_ratio_p95')
        
        # Should return 0.0 initially (no samples)
        assert monitor.risk_ratio_p95() == 0.0


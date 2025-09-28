"""Test markout metrics accumulation."""

import pytest
from unittest.mock import Mock, patch
from prometheus_client import REGISTRY
from src.metrics.exporter import Metrics
from src.common.di import AppContext


class TestMarkoutAccumulate:
    """Test markout metrics accumulation and averaging."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear prometheus registry to avoid duplicate metrics
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        
        self.ctx = Mock(spec=AppContext)
        self.metrics = Metrics(self.ctx)
    
    def test_record_markout_basic(self):
        """Test basic markout recording."""
        # Record markout for BTCUSDT, blue, positive markout
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)
        
        # Check counters
        assert self.metrics.markout_up_total.labels(horizon_ms="200", color="blue", symbol="BTCUSDT")._value.get() == 1
        assert self.metrics.markout_down_total.labels(horizon_ms="200", color="blue", symbol="BTCUSDT")._value.get() == 0
        assert self.metrics.markout_up_total.labels(horizon_ms="500", color="blue", symbol="BTCUSDT")._value.get() == 1
        assert self.metrics.markout_down_total.labels(horizon_ms="500", color="blue", symbol="BTCUSDT")._value.get() == 0
        
        # Check gauges (markout_200 = (50025-50000)/50000 * 10000 = 5.0 bps)
        assert abs(self.metrics.markout_avg_bps.labels(horizon_ms="200", color="blue", symbol="BTCUSDT")._value.get() - 5.0) < 0.001
        # markout_500 = (50050-50000)/50000 * 10000 = 10.0 bps
        assert abs(self.metrics.markout_avg_bps.labels(horizon_ms="500", color="blue", symbol="BTCUSDT")._value.get() - 10.0) < 0.001
    
    def test_record_markout_negative(self):
        """Test negative markout recording."""
        # Record markout for BTCUSDT, green, negative markout
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49975.0, 49950.0)
        
        # Check counters
        assert self.metrics.markout_up_total.labels(horizon_ms="200", color="green", symbol="BTCUSDT")._value.get() == 0
        assert self.metrics.markout_down_total.labels(horizon_ms="200", color="green", symbol="BTCUSDT")._value.get() == 1
        assert self.metrics.markout_up_total.labels(horizon_ms="500", color="green", symbol="BTCUSDT")._value.get() == 0
        assert self.metrics.markout_down_total.labels(horizon_ms="500", color="green", symbol="BTCUSDT")._value.get() == 1
        
        # Check gauges (markout_200 = (49975-50000)/50000 * 10000 = -5.0 bps)
        assert abs(self.metrics.markout_avg_bps.labels(horizon_ms="200", color="green", symbol="BTCUSDT")._value.get() - (-5.0)) < 0.001
        # markout_500 = (49950-50000)/50000 * 10000 = -10.0 bps
        assert abs(self.metrics.markout_avg_bps.labels(horizon_ms="500", color="green", symbol="BTCUSDT")._value.get() - (-10.0)) < 0.001
    
    def test_record_markout_multiple_samples(self):
        """Test markout averaging across multiple samples."""
        # Record multiple markouts for same symbol/color/horizon
        # 200ms: (3003-3000)/3000*10000 = 10.0 bps, (3006-3000)/3000*10000 = 20.0 bps, (3009-3000)/3000*10000 = 30.0 bps
        # 500ms: (3006-3000)/3000*10000 = 20.0 bps, (3012-3000)/3000*10000 = 40.0 bps, (3018-3000)/3000*10000 = 60.0 bps
        self.metrics.record_markout("ETHUSDT", "blue", 3000.0, 3000.0, 3003.0, 3006.0)
        self.metrics.record_markout("ETHUSDT", "blue", 3000.0, 3000.0, 3006.0, 3012.0)
        self.metrics.record_markout("ETHUSDT", "blue", 3000.0, 3000.0, 3009.0, 3018.0)
        
        # Check counters
        assert self.metrics.markout_up_total.labels(horizon_ms="200", color="blue", symbol="ETHUSDT")._value.get() == 3
        assert self.metrics.markout_up_total.labels(horizon_ms="500", color="blue", symbol="ETHUSDT")._value.get() == 3
        
        # Check gauges (average: 200ms = (10+20+30)/3 = 20.0 bps, 500ms = (20+40+60)/3 = 40.0 bps)
        assert abs(self.metrics.markout_avg_bps.labels(horizon_ms="200", color="blue", symbol="ETHUSDT")._value.get() - 20.0) < 0.001
        assert abs(self.metrics.markout_avg_bps.labels(horizon_ms="500", color="blue", symbol="ETHUSDT")._value.get() - 40.0) < 0.001
    
    def test_record_markout_mixed_colors(self):
        """Test markout recording for different colors."""
        # Record markout for blue
        self.metrics.record_markout("ADAUSDT", "blue", 0.5, 0.5, 0.501, 0.502)
        # Record markout for green
        self.metrics.record_markout("ADAUSDT", "green", 0.5, 0.5, 0.499, 0.498)
        
        # Check blue metrics
        assert self.metrics.markout_up_total.labels(horizon_ms="200", color="blue", symbol="ADAUSDT")._value.get() == 1
        assert self.metrics.markout_up_total.labels(horizon_ms="500", color="blue", symbol="ADAUSDT")._value.get() == 1
        
        # Check green metrics
        assert self.metrics.markout_down_total.labels(horizon_ms="200", color="green", symbol="ADAUSDT")._value.get() == 1
        assert self.metrics.markout_down_total.labels(horizon_ms="500", color="green", symbol="ADAUSDT")._value.get() == 1
        
        # Check gauges are separate
        blue_200 = self.metrics.markout_avg_bps.labels(horizon_ms="200", color="blue", symbol="ADAUSDT")._value.get()
        green_200 = self.metrics.markout_avg_bps.labels(horizon_ms="200", color="green", symbol="ADAUSDT")._value.get()
        assert blue_200 > 0  # Positive markout
        assert green_200 < 0  # Negative markout
    
    def test_record_markout_different_symbols(self):
        """Test markout recording for different symbols."""
        # Record markout for BTCUSDT
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)
        # Record markout for SOLUSDT
        self.metrics.record_markout("SOLUSDT", "blue", 100.0, 100.0, 100.1, 100.2)
        
        # Check metrics are separate per symbol
        btc_200 = self.metrics.markout_avg_bps.labels(horizon_ms="200", color="blue", symbol="BTCUSDT")._value.get()
        sol_200 = self.metrics.markout_avg_bps.labels(horizon_ms="200", color="blue", symbol="SOLUSDT")._value.get()
        
        assert abs(btc_200 - 5.0) < 0.001  # (50025-50000)/50000 * 10000
        assert abs(sol_200 - 10.0) < 0.001  # (100.1-100.0)/100.0 * 10000
    
    def test_record_markout_edge_cases(self):
        """Test markout edge cases."""
        # Zero execution price (should not crash)
        self.metrics.record_markout("TEST", "blue", 0.0, 0.0, 1.0, 2.0)
        
        # Very small price differences
        self.metrics.record_markout("TEST", "green", 1.0, 1.0, 1.000001, 1.000002)
        
        # Large price differences
        self.metrics.record_markout("TEST", "blue", 1.0, 1.0, 2.0, 3.0)
        
        # All should complete without errors
        assert True
    
    def test_markout_snapshot_deterministic(self):
        """Test that markout snapshot is deterministic."""
        # Record some markouts
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)
        self.metrics.record_markout("ETHUSDT", "green", 3000.0, 3000.0, 3003.0, 3006.0)
        
        # Get snapshot multiple times
        snap1 = self.metrics._get_markout_snapshot_for_tests()
        snap2 = self.metrics._get_markout_snapshot_for_tests()
        
        # Should be identical
        assert snap1 == snap2
        
        # Check structure
        assert "200" in snap1
        assert "500" in snap1
        assert "blue" in snap1["200"]
        assert "green" in snap1["200"]
        assert "BTCUSDT" in snap1["200"]["blue"]
        assert "ETHUSDT" in snap1["200"]["green"]
        
        # Check data integrity
        btc_data = snap1["200"]["blue"]["BTCUSDT"]
        assert btc_data["count"] == 1
        assert abs(btc_data["avg_bps"] - 5.0) < 0.001
        assert btc_data["sum_bps_int"] == 50000  # 5.0 * 10000
    
    def test_markout_snapshot_empty(self):
        """Test markout snapshot when no data exists."""
        snap = self.metrics._get_markout_snapshot_for_tests()

        # Should return structure with samples: 0 when no data exists
        assert snap == {"200": {"blue": {"samples": 0}, "green": {"samples": 0}}, "500": {"blue": {"samples": 0}, "green": {"samples": 0}}}
    
    def test_markout_snapshot_symbols_sorted(self):
        """Test that symbols are sorted in snapshot."""
        # Record markouts in random order
        self.metrics.record_markout("ZECUSDT", "blue", 100.0, 100.0, 100.1, 100.2)
        self.metrics.record_markout("ADAUSDT", "blue", 0.5, 0.5, 0.501, 0.502)
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)
        
        snap = self.metrics._get_markout_snapshot_for_tests()
        
        # Symbols should be sorted lexicographically (excluding 'samples' field)
        symbols = [k for k in snap["200"]["blue"].keys() if k != "samples"]
        assert symbols == ["ADAUSDT", "BTCUSDT", "ZECUSDT"]

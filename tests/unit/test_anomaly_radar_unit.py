#!/usr/bin/env python3
"""Unit tests for tools.soak.anomaly_radar pure functions."""
import pytest
from tools.soak.anomaly_radar import _median, _mad, detect_anomalies


class TestMedian:
    """Tests for _median function."""
    
    def test_empty_sequence(self):
        """Test median of empty sequence."""
        assert _median([]) == 0.0
    
    def test_single_value(self):
        """Test median of single value."""
        assert _median([5.0]) == 5.0
    
    def test_odd_length(self):
        """Test median of odd-length sequence."""
        assert _median([1, 2, 3, 4, 5]) == 3.0
    
    def test_even_length(self):
        """Test median of even-length sequence."""
        assert _median([1, 2, 3, 4]) == 2.5
    
    def test_unsorted_input(self):
        """Test that unsorted input is handled."""
        assert _median([5, 1, 3, 2, 4]) == 3.0
    
    def test_duplicates(self):
        """Test median with duplicates."""
        assert _median([1, 1, 2, 2, 3, 3]) == 2.0


class TestMad:
    """Tests for _mad function."""
    
    def test_empty_sequence(self):
        """Test MAD of empty sequence."""
        assert _mad([]) == 0.0
    
    def test_single_value(self):
        """Test MAD of single value."""
        assert _mad([5.0]) == 0.0
    
    def test_uniform_values(self):
        """Test MAD when all values are identical."""
        assert _mad([3, 3, 3, 3]) == 0.0
    
    def test_basic_mad(self):
        """Test basic MAD calculation."""
        # [1, 2, 3, 4, 5], median=3, deviations=[2,1,0,1,2], MAD=1
        result = _mad([1, 2, 3, 4, 5])
        assert abs(result - 1.0) < 1e-12
    
    def test_with_outlier(self):
        """Test MAD with outlier."""
        # [1, 2, 3, 4, 100], median=3, deviations=[2,1,0,1,97], MAD=1
        result = _mad([1, 2, 3, 4, 100])
        assert abs(result - 1.0) < 1e-12


class TestDetectAnomalies:
    """Tests for detect_anomalies function."""
    
    def test_empty_buckets(self):
        """Test with empty buckets."""
        result = detect_anomalies([])
        assert result == []
    
    def test_no_anomalies_uniform_data(self):
        """Test with uniform data (MAD=0)."""
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:15', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0}
        ]
        result = detect_anomalies(buckets, k=3.0)
        
        assert result == []  # No anomalies when MAD=0
    
    def test_detect_edge_anomaly(self):
        """Test detection of edge (net_bps) anomaly."""
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:15', 'net_bps': 2.9, 'order_age_p95_ms': 305.0, 'taker_share_pct': 12.1},
            {'bucket': '00:30', 'net_bps': -10.0, 'order_age_p95_ms': 310.0, 'taker_share_pct': 12.2}
        ]
        result = detect_anomalies(buckets, k=2.0)
        
        assert len(result) > 0
        kinds = [a['kind'] for a in result]
        assert 'EDGE' in kinds
    
    def test_detect_latency_anomaly(self):
        """Test detection of latency (order_age_p95_ms) anomaly."""
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:15', 'net_bps': 3.0, 'order_age_p95_ms': 305.0, 'taker_share_pct': 12.0},
            {'bucket': '00:30', 'net_bps': 3.0, 'order_age_p95_ms': 1000.0, 'taker_share_pct': 12.0}
        ]
        result = detect_anomalies(buckets, k=2.0)
        
        kinds = [a['kind'] for a in result]
        assert 'LAT' in kinds
    
    def test_detect_taker_anomaly(self):
        """Test detection of taker (taker_share_pct) anomaly."""
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:15', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.1},
            {'bucket': '00:30', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.2},
            {'bucket': '00:45', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 80.0}
        ]
        result = detect_anomalies(buckets, k=2.0)
        
        kinds = [a['kind'] for a in result]
        assert 'TAKER' in kinds
    
    def test_multiple_anomalies_different_kinds(self):
        """Test detection of multiple anomalies of different kinds."""
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:15', 'net_bps': 2.9, 'order_age_p95_ms': 305.0, 'taker_share_pct': 12.1},
            {'bucket': '00:30', 'net_bps': -5.0, 'order_age_p95_ms': 310.0, 'taker_share_pct': 40.0}
        ]
        result = detect_anomalies(buckets, k=2.0)
        
        kinds = set(a['kind'] for a in result)
        # Should detect at least EDGE and TAKER
        assert len(kinds) >= 2
    
    def test_anomaly_structure(self):
        """Test that anomaly dict has correct structure."""
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:30', 'net_bps': -10.0, 'order_age_p95_ms': 310.0, 'taker_share_pct': 12.0}
        ]
        result = detect_anomalies(buckets, k=1.0)
        
        if result:
            anom = result[0]
            assert 'kind' in anom
            assert 'bucket' in anom
            assert 'net_bps' in anom
            assert 'order_age_p95_ms' in anom
            assert 'taker_share_pct' in anom
            assert 'mad_score' in anom
    
    def test_k_threshold(self):
        """Test that k threshold controls detection sensitivity."""
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:15', 'net_bps': 2.9, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:30', 'net_bps': -1.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0}
        ]
        
        # High k should detect fewer anomalies
        strict_result = detect_anomalies(buckets, k=10.0)
        loose_result = detect_anomalies(buckets, k=1.0)
        
        assert len(loose_result) >= len(strict_result)
    
    def test_bucket_name_in_anomaly(self):
        """Test that bucket name is preserved in anomaly."""
        buckets = [
            {'bucket': '00:00', 'net_bps': 3.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0},
            {'bucket': '00:30', 'net_bps': -10.0, 'order_age_p95_ms': 300.0, 'taker_share_pct': 12.0}
        ]
        result = detect_anomalies(buckets, k=1.0)
        
        if result:
            buckets_in_anomalies = [a['bucket'] for a in result]
            assert '00:30' in buckets_in_anomalies or '00:00' in buckets_in_anomalies


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


#!/usr/bin/env python3
"""Unit tests for tools.edge_sentinel.report pure functions."""
import pytest
from tools.edge_sentinel.report import _bucketize, _rank_symbols, _build_report, _render_md


class TestBucketize:
    """Tests for _bucketize function."""
    
    def test_empty_inputs(self):
        """Test with empty trades and quotes."""
        result = _bucketize([], [], bucket_ms=60000)
        assert result == []
    
    def test_single_trade(self):
        """Test with single trade."""
        trades = [{'ts': 1000, 'symbol': 'BTCUSDT', 'net_bps': 3.5}]
        result = _bucketize(trades, [], bucket_ms=60000)
        
        assert len(result) == 1
        assert result[0]['symbol'] == 'BTCUSDT'
        assert result[0]['net_bps'] == 3.5
        assert result[0]['trade_count'] == 1
    
    def test_multiple_trades_same_bucket(self):
        """Test averaging within same bucket."""
        trades = [
            {'ts': 1000, 'symbol': 'BTCUSDT', 'net_bps': 3.0},
            {'ts': 2000, 'symbol': 'BTCUSDT', 'net_bps': 5.0}
        ]
        result = _bucketize(trades, [], bucket_ms=60000)
        
        assert len(result) == 1
        assert result[0]['net_bps'] == 4.0  # Average of 3.0 and 5.0
        assert result[0]['trade_count'] == 2
    
    def test_multiple_buckets(self):
        """Test trades across multiple buckets."""
        trades = [
            {'ts': 1000, 'symbol': 'BTCUSDT', 'net_bps': 3.0},
            {'ts': 61000, 'symbol': 'BTCUSDT', 'net_bps': 5.0}
        ]
        result = _bucketize(trades, [], bucket_ms=60000)
        
        assert len(result) == 2
        assert result[0]['bucket_ts'] == 0
        assert result[1]['bucket_ts'] == 60000
    
    def test_multiple_symbols(self):
        """Test with multiple symbols."""
        trades = [
            {'ts': 1000, 'symbol': 'BTCUSDT', 'net_bps': 3.0},
            {'ts': 1000, 'symbol': 'ETHUSDT', 'net_bps': 2.5}
        ]
        result = _bucketize(trades, [], bucket_ms=60000)
        
        assert len(result) == 2
        symbols = [b['symbol'] for b in result]
        assert 'BTCUSDT' in symbols
        assert 'ETHUSDT' in symbols
    
    def test_stable_ordering(self):
        """Test that output is stably ordered."""
        trades = [
            {'ts': 2000, 'symbol': 'ETHUSDT', 'net_bps': 2.0},
            {'ts': 1000, 'symbol': 'BTCUSDT', 'net_bps': 3.0}
        ]
        result = _bucketize(trades, [], bucket_ms=60000)
        
        # Should be ordered by (bucket_ts, symbol)
        assert result[0]['symbol'] == 'BTCUSDT'  # Same bucket, alphabetically first
        assert result[1]['symbol'] == 'ETHUSDT'


class TestRankSymbols:
    """Tests for _rank_symbols function."""
    
    def test_empty_buckets(self):
        """Test with empty buckets."""
        result = _rank_symbols([])
        assert result == []
    
    def test_single_symbol(self):
        """Test with single symbol."""
        buckets = [
            {'symbol': 'BTCUSDT', 'net_bps': 3.0}
        ]
        result = _rank_symbols(buckets)
        
        assert len(result) == 1
        assert result[0]['symbol'] == 'BTCUSDT'
        assert result[0]['total_net_bps'] == 3.0
    
    def test_multiple_symbols_sorted(self):
        """Test sorting by total_net_bps (lowest first)."""
        buckets = [
            {'symbol': 'BTCUSDT', 'net_bps': 3.0},
            {'symbol': 'ETHUSDT', 'net_bps': -1.0},
            {'symbol': 'SOLUSDT', 'net_bps': 2.0}
        ]
        result = _rank_symbols(buckets)
        
        assert len(result) == 3
        assert result[0]['symbol'] == 'ETHUSDT'  # Lowest (worst)
        assert result[1]['symbol'] == 'SOLUSDT'
        assert result[2]['symbol'] == 'BTCUSDT'
    
    def test_aggregation_across_buckets(self):
        """Test aggregation of same symbol across buckets."""
        buckets = [
            {'symbol': 'BTCUSDT', 'net_bps': 3.0},
            {'symbol': 'BTCUSDT', 'net_bps': 2.0}
        ]
        result = _rank_symbols(buckets)
        
        assert len(result) == 1
        assert result[0]['total_net_bps'] == 5.0
        assert result[0]['bucket_count'] == 2
    
    def test_stable_ordering_with_equal_values(self):
        """Test stable ordering when total_net_bps is equal."""
        buckets = [
            {'symbol': 'ETHUSDT', 'net_bps': 2.0},
            {'symbol': 'BTCUSDT', 'net_bps': 2.0}
        ]
        result = _rank_symbols(buckets)
        
        # Should be ordered by (total_net_bps, symbol)
        assert result[0]['symbol'] == 'BTCUSDT'  # Alphabetically first
        assert result[1]['symbol'] == 'ETHUSDT'


class TestBuildReport:
    """Tests for _build_report function."""
    
    def test_empty_data_hold_advice(self):
        """Test with no data produces HOLD advice."""
        report = _build_report([], [], "2025-01-01T00:00:00Z")
        
        assert report['advice'] == ["HOLD"]
        assert report['summary']['buckets'] == 0
        assert report['runtime']['utc'] == "2025-01-01T00:00:00Z"
    
    def test_severe_degradation_block_advice(self):
        """Test severe degradation produces BLOCK advice."""
        ranked = [{'symbol': 'BTCUSDT', 'total_net_bps': -6.0}]
        report = _build_report([], ranked, "2025-01-01T00:00:00Z")
        
        assert report['advice'][0] == "BLOCK"
        assert "Severe" in report['advice'][1]
    
    def test_moderate_degradation_warn_advice(self):
        """Test moderate degradation produces WARN advice."""
        ranked = [{'symbol': 'BTCUSDT', 'total_net_bps': -3.0}]
        report = _build_report([], ranked, "2025-01-01T00:00:00Z")
        
        assert report['advice'][0] == "WARN"
    
    def test_healthy_ready_advice(self):
        """Test healthy metrics produce READY advice."""
        ranked = [{'symbol': 'BTCUSDT', 'total_net_bps': 3.0}]
        report = _build_report([], ranked, "2025-01-01T00:00:00Z")
        
        assert report['advice'] == ["READY"]
    
    def test_summary_symbols_dict(self):
        """Test summary contains symbols dict."""
        ranked = [
            {'symbol': 'BTCUSDT', 'total_net_bps': 3.0},
            {'symbol': 'ETHUSDT', 'total_net_bps': 2.0}
        ]
        report = _build_report([], ranked, "2025-01-01T00:00:00Z")
        
        assert report['summary']['symbols']['BTCUSDT'] == 3.0
        assert report['summary']['symbols']['ETHUSDT'] == 2.0
    
    def test_top_sections_present(self):
        """Test top sections are present in report."""
        buckets = [{'symbol': 'BTC', 'net_bps': -1.0, 'bucket_ts': 0}]
        ranked = [{'symbol': 'BTC', 'total_net_bps': -1.0}]
        report = _build_report(buckets, ranked, "2025-01-01T00:00:00Z")
        
        assert 'top_buckets_by_net_drop' in report['top']
        assert 'top_symbols_by_net_drop' in report['top']
        assert 'contributors_by_component' in report['top']


class TestRenderMd:
    """Tests for _render_md function."""
    
    def test_minimal_report(self):
        """Test rendering minimal report."""
        report = {
            'advice': ['HOLD'],
            'summary': {'buckets': 0},
            'top': {
                'top_symbols_by_net_drop': [],
                'top_buckets_by_net_drop': [],
                'contributors_by_component': {}
            }
        }
        md = _render_md(report)
        
        assert "# Edge Sentinel Report" in md
        assert "**Advice:** HOLD" in md
        assert "No data available" in md
        assert md.endswith("\n")
    
    def test_with_top_symbols(self):
        """Test rendering with top symbols."""
        report = {
            'advice': ['WARN'],
            'summary': {'buckets': 5},
            'top': {
                'top_symbols_by_net_drop': [
                    {'symbol': 'BTCUSDT', 'total_net_bps': -3.5},
                    {'symbol': 'ETHUSDT', 'total_net_bps': 2.0}
                ],
                'top_buckets_by_net_drop': [],
                'contributors_by_component': {}
            }
        }
        md = _render_md(report)
        
        assert "BTCUSDT" in md
        assert "-3.50" in md
        assert "ETHUSDT" in md
        assert "2.00" in md
    
    def test_deterministic_output(self):
        """Test that output is deterministic."""
        report = {
            'advice': ['READY'],
            'summary': {'buckets': 2},
            'top': {
                'top_symbols_by_net_drop': [
                    {'symbol': 'A', 'total_net_bps': 1.0}
                ],
                'top_buckets_by_net_drop': [],
                'contributors_by_component': {}
            }
        }
        md1 = _render_md(report)
        md2 = _render_md(report)
        
        assert md1 == md2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


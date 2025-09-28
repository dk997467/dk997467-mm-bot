"""
Tests for E1+ Prometheus metrics integration.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.storage.research_recorder import ResearchRecorder
from src.common.models import OrderBook, PriceLevel
from decimal import Decimal


class TestPromMetrics:
    """Test Prometheus metrics functionality."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = MagicMock()
        config.storage = MagicMock()
        config.storage.compress = 'none'
        config.storage.batch_size = 100
        config.storage.flush_ms = 50
        return config

    @pytest.fixture
    def mock_prometheus_counters(self):
        """Mock Prometheus counters for testing."""
        with patch('src.storage.research_recorder.summaries_written_total') as written_mock, \
             patch('src.storage.research_recorder.summaries_pruned_total') as pruned_mock, \
             patch('src.storage.research_recorder.summary_write_errors_total') as errors_mock:
            
            # Configure mocks to track calls
            written_mock.labels.return_value.inc = MagicMock()
            pruned_mock.labels.return_value.inc = MagicMock()
            errors_mock.labels.return_value.inc = MagicMock()
            
            yield {
                'written': written_mock,
                'pruned': pruned_mock,
                'errors': errors_mock
            }

    @pytest.fixture
    async def recorder(self, tmp_path, mock_config, mock_prometheus_counters):
        """Create a test recorder instance with mocked metrics."""
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            retention_days=2,  # Short retention for testing pruning
            lock_mode="none"
        )
        await recorder.start()
        yield recorder
        await recorder.stop()

    def create_test_orderbook(self, symbol: str = "METRICS", mid_price: float = 50.0) -> OrderBook:
        """Create a test orderbook."""
        return OrderBook(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=3000,
            bids=[PriceLevel(price=Decimal(str(mid_price - 0.01)), size=Decimal("1.0"))],
            asks=[PriceLevel(price=Decimal(str(mid_price + 0.01)), size=Decimal("1.0"))]
        )

    @pytest.mark.asyncio
    async def test_summaries_written_total_metric(self, recorder, tmp_path, mock_prometheus_counters):
        """Test that summaries_written_total metric is incremented on successful writes."""
        symbol = "WRITTEN"
        
        # Generate test data
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 49.99, "size": 1.0}], "asks": []}
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
        
        test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='metrics_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='metrics_hash'):
            await recorder._generate_hourly_summaries(test_hour)
        
        # Verify metric was incremented
        written_counter = mock_prometheus_counters['written']
        written_counter.labels.assert_called_with(symbol=symbol)
        written_counter.labels.return_value.inc.assert_called_with()

    @pytest.mark.asyncio
    async def test_summaries_pruned_total_metric(self, recorder, tmp_path, mock_prometheus_counters):
        """Test that summaries_pruned_total metric is incremented when files are pruned."""
        symbol = "PRUNED"
        
        # Create symbol directory with old files
        symbol_dir = tmp_path / "summaries" / symbol
        symbol_dir.mkdir(parents=True)
        
        # Create mock old files (simulate files from 5 days ago)
        old_time = datetime.now(timezone.utc) - timedelta(days=5)
        for hour in range(5):
            file_time = old_time.replace(hour=hour)
            filename = f"{symbol}_{file_time.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            # Create file with minimal content
            mock_data = {
                "symbol": symbol,
                "hour_utc": file_time.isoformat() + "Z",
                "counts": {"orders": 1, "quotes": 1, "fills": 0},
                "hit_rate_by_bin": {},
                "queue_wait_cdf_ms": [],
                "metadata": {"git_sha": "old", "cfg_hash": "old"}
            }
            
            with open(file_path, 'w') as f:
                import json
                json.dump(mock_data, f)
            
            # Set old modification time
            import os
            old_timestamp = old_time.timestamp()
            os.utime(file_path, (old_timestamp, old_timestamp))
        
        # Trigger pruning by writing a new summary
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 49.99, "size": 1.0}], "asks": []}
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
        
        test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='prune_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='prune_hash'):
            await recorder._generate_hourly_summaries(test_hour)
        
        # Verify pruning metric was incremented
        pruned_counter = mock_prometheus_counters['pruned']
        pruned_counter.labels.assert_called_with(symbol=symbol)
        # Should be called with count of pruned files (5)
        pruned_counter.labels.return_value.inc.assert_called_with(5)

    @pytest.mark.asyncio
    async def test_summary_write_errors_total_metric(self, recorder, tmp_path, mock_prometheus_counters):
        """Test that summary_write_errors_total metric is incremented on validation failures."""
        symbol = "ERRORS"
        
        # Mock validation to fail
        with patch('src.storage.validators.validate_summary_payload', return_value=(False, ["Test validation error"])):
            
            # Generate test data that will fail validation
            orderbook = self.create_test_orderbook(symbol)
            our_quotes = {"bids": [{"price": 49.99, "size": 1.0}], "asks": []}
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
            
            test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='error_sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='error_hash'):
                await recorder._generate_hourly_summaries(test_hour)
        
        # Verify error metric was incremented
        errors_counter = mock_prometheus_counters['errors']
        errors_counter.labels.assert_called_with(symbol=symbol)
        errors_counter.labels.return_value.inc.assert_called_with()

    @pytest.mark.asyncio
    async def test_metrics_with_multiple_symbols(self, recorder, tmp_path, mock_prometheus_counters):
        """Test that metrics are correctly labeled by symbol."""
        symbols = ["SYM1", "SYM2", "SYM3"]
        
        # Generate data for multiple symbols
        for symbol in symbols:
            orderbook = self.create_test_orderbook(symbol)
            our_quotes = {"bids": [{"price": 49.99, "size": 1.0}], "asks": []}
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
        
        test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='multi_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='multi_hash'):
            await recorder._generate_hourly_summaries(test_hour)
        
        # Verify each symbol got its own metric increment
        written_counter = mock_prometheus_counters['written']
        assert written_counter.labels.call_count == len(symbols)
        
        for symbol in symbols:
            written_counter.labels.assert_any_call(symbol=symbol)

    def test_prometheus_unavailable_fallback(self, tmp_path, mock_config):
        """Test graceful fallback when prometheus_client is unavailable."""
        # Mock prometheus_client import failure
        with patch.dict('sys.modules', {'prometheus_client': None}):
            with patch('src.storage.research_recorder.prometheus_available', False):
                
                # Should not raise exception
                recorder = ResearchRecorder(
                    mock_config,
                    str(tmp_path / "research"),
                    summaries_dir=str(tmp_path / "summaries")
                )
                
                # Should have mock counters that do nothing
                assert hasattr(recorder, 'summaries_written')  # From recorder stats
                
                # Mock counters should be callable without error
                from src.storage.research_recorder import summaries_written_total
                summaries_written_total.labels(symbol="TEST").inc()  # Should not crash

    @pytest.mark.asyncio
    async def test_metric_cardinality_control(self, recorder, tmp_path, mock_prometheus_counters):
        """Test that metrics use only symbol as label (low cardinality)."""
        symbol = "CARDINALITY"
        
        # Generate data
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 49.99, "size": 1.0}], "asks": []}
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
        
        test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='card_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='card_hash'):
            await recorder._generate_hourly_summaries(test_hour)
        
        # Verify only symbol label is used (no high-cardinality labels like timestamp, etc.)
        written_counter = mock_prometheus_counters['written']
        written_counter.labels.assert_called_with(symbol=symbol)
        
        # Ensure no other arguments were passed
        call_args = written_counter.labels.call_args
        assert len(call_args[1]) == 1  # Only one keyword argument
        assert 'symbol' in call_args[1]  # And it should be 'symbol'

    @pytest.mark.asyncio 
    async def test_metrics_with_concurrent_writes(self, tmp_path, mock_config, mock_prometheus_counters):
        """Test metrics behavior with concurrent recorder instances."""
        symbol = "CONCURRENT"
        
        # Create two recorders
        recorder1 = ResearchRecorder(
            mock_config,
            str(tmp_path / "research1"),
            summaries_dir=str(tmp_path / "summaries"),
            lock_mode="none",
            retention_days=None
        )
        
        recorder2 = ResearchRecorder(
            mock_config,
            str(tmp_path / "research2"),
            summaries_dir=str(tmp_path / "summaries"),
            lock_mode="none",
            retention_days=None
        )
        
        await recorder1.start()
        await recorder2.start()
        
        try:
            # Both write data
            orderbook = self.create_test_orderbook(symbol)
            our_quotes1 = {"bids": [{"price": 49.99, "size": 1.0}], "asks": []}
            our_quotes2 = {"bids": [{"price": 49.98, "size": 1.0}], "asks": []}
            
            recorder1.record_market_snapshot(symbol, orderbook, our_quotes1, 0.1)
            recorder2.record_market_snapshot(symbol, orderbook, our_quotes2, 0.1)
            
            test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='conc_sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='conc_hash'):
                await recorder1._generate_hourly_summaries(test_hour)
                await recorder2._generate_hourly_summaries(test_hour)
            
            # Metrics should be incremented for both writes
            written_counter = mock_prometheus_counters['written']
            assert written_counter.labels.return_value.inc.call_count == 2
            
        finally:
            await recorder1.stop()
            await recorder2.stop()

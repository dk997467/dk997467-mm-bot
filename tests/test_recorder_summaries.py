"""Tests for research recorder hourly summaries and binning logic."""

import json
import tempfile
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.storage.research_recorder import ResearchRecorder
from src.common.config import AppConfig
from src.common.models import OrderBook, PriceLevel, Order, Side


class TestRecorderSummaries:
    """Test research recorder summary generation."""
    
    def test_price_bin_calculation(self):
        """Test price bin calculation logic."""
        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.storage = MagicMock()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = ResearchRecorder(config, temp_dir)
            
            # Test price binning
            mid_price = 50000.0
            
            # Test exact mid price
            assert recorder._calculate_price_bin_bps(50000.0, mid_price) == 0
            
            # Test 5 bps from mid
            assert recorder._calculate_price_bin_bps(50025.0, mid_price) == 5  # +5 bps
            assert recorder._calculate_price_bin_bps(49975.0, mid_price) == 5  # -5 bps
            
            # Test 10 bps from mid
            assert recorder._calculate_price_bin_bps(50050.0, mid_price) == 10
            assert recorder._calculate_price_bin_bps(49950.0, mid_price) == 10
            
            # Test capped at 50 bps
            assert recorder._calculate_price_bin_bps(50300.0, mid_price) == 50  # Would be 60 bps
            assert recorder._calculate_price_bin_bps(49700.0, mid_price) == 50  # Would be 60 bps
            
            # Test edge case with zero mid price
            assert recorder._calculate_price_bin_bps(100.0, 0.0) == 0
    
    @pytest.mark.asyncio
    async def test_hourly_summary_generation(self):
        """Test generation of hourly summary files."""
        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.storage = MagicMock()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = ResearchRecorder(config, temp_dir)
            
            # Mock git_sha and cfg_hash functions
            with patch('src.storage.research_recorder.get_git_sha', return_value='test_sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='test_hash'):
                
                # Setup test data
                symbol = "BTCUSDT"
                test_hour = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
                
                # Add test data to hourly buffer
                recorder.hourly_data[symbol] = {
                    "orders": [
                        {"price_bin_bps": 5, "timestamp": "2025-01-15T14:15:00Z"},
                        {"price_bin_bps": 10, "timestamp": "2025-01-15T14:30:00Z"},
                        {"price_bin_bps": 5, "timestamp": "2025-01-15T14:45:00Z"}
                    ],
                    "quotes": [
                        {"price_bin_bps": 5, "timestamp": "2025-01-15T14:10:00Z"},
                        {"price_bin_bps": 5, "timestamp": "2025-01-15T14:20:00Z"},
                        {"price_bin_bps": 10, "timestamp": "2025-01-15T14:25:00Z"},
                        {"price_bin_bps": 10, "timestamp": "2025-01-15T14:35:00Z"},
                        {"price_bin_bps": 15, "timestamp": "2025-01-15T14:40:00Z"}
                    ],
                    "fills": [
                        {"price_bin_bps": 5, "timestamp": "2025-01-15T14:15:30Z"},
                        {"price_bin_bps": 10, "timestamp": "2025-01-15T14:35:30Z"}
                    ],
                    "queue_waits": [150.0, 250.0, 180.0, 300.0, 120.0, 400.0, 200.0]
                }
                
                # Generate summary
                await recorder._generate_hourly_summaries(test_hour)
                
                # Check that summary file was created
                summary_path = Path(temp_dir) / "summaries" / symbol / f"{symbol}_2025-01-15_14.json"
                assert summary_path.exists()
                
                # Read and validate summary content
                with open(summary_path, 'r') as f:
                    summary = json.load(f)
                
                # Validate schema
                assert summary["symbol"] == symbol
                assert summary["hour_utc"] == "2025-01-15T14:00:00Z"
                
                # Validate counts
                assert summary["counts"]["orders"] == 3
                assert summary["counts"]["quotes"] == 5
                assert summary["counts"]["fills"] == 2
                
                # Validate hit rate by bin
                hit_rates = summary["hit_rate_by_bin"]
                assert "5" in hit_rates
                assert "10" in hit_rates
                assert "15" in hit_rates
                
                # 5 bps bin: 2 quotes, 1 fill
                assert hit_rates["5"]["count"] == 2
                assert hit_rates["5"]["fills"] == 1
                
                # 10 bps bin: 2 quotes, 1 fill
                assert hit_rates["10"]["count"] == 2
                assert hit_rates["10"]["fills"] == 1
                
                # 15 bps bin: 1 quote, 0 fills
                assert hit_rates["15"]["count"] == 1
                assert hit_rates["15"]["fills"] == 0
                
                # Validate queue wait CDF
                cdf = summary["queue_wait_cdf_ms"]
                assert len(cdf) == 4  # 0.5, 0.9, 0.95, 0.99
                
                # Check percentile structure
                for point in cdf:
                    assert "p" in point
                    assert "v" in point
                    assert 0 <= point["p"] <= 1
                    assert point["v"] >= 0
                
                # Validate metadata
                assert summary["metadata"]["git_sha"] == "test_sha"
                assert summary["metadata"]["cfg_hash"] == "test_hash"
                
                # Validate JSON determinism (sorted keys)
                json_str = json.dumps(summary, sort_keys=True, ensure_ascii=False)
                assert '"cfg_hash"' in json_str
                assert '"git_sha"' in json_str
    
    @pytest.mark.asyncio
    async def test_record_order_event_with_binning(self):
        """Test that order events are properly binned."""
        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.storage = MagicMock()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = ResearchRecorder(config, temp_dir)
            
            # Create test order
            order = Order(
                order_id="test123",
                symbol="BTCUSDT",
                side=Side.BUY,
                price=50025.0,  # 5 bps from mid
                qty=1.0,
                timestamp=datetime.now(timezone.utc)
            )
            
            # Record order creation event
            recorder.record_order_event(
                event_type="create",
                order=order,
                mid_price=50000.0
            )
            
            # Check that order was added to hourly data with correct bin
            symbol_data = recorder.hourly_data["BTCUSDT"]
            assert len(symbol_data["orders"]) == 1
            assert symbol_data["orders"][0]["price_bin_bps"] == 5
            
            # Record fill event with queue wait time
            recorder.record_order_event(
                event_type="fill",
                order=order,
                queue_wait_ms=250.0,
                mid_price=50000.0
            )
            
            # Check that fill was recorded
            assert len(symbol_data["fills"]) == 1
            assert symbol_data["fills"][0]["price_bin_bps"] == 5
            
            # Check that queue wait was recorded
            assert len(symbol_data["queue_waits"]) == 1
            assert symbol_data["queue_waits"][0] == 250.0
    
    @pytest.mark.asyncio
    async def test_record_market_snapshot_with_quotes(self):
        """Test market snapshot recording with quote binning."""
        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.storage = MagicMock()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = ResearchRecorder(config, temp_dir)
            
            # Create test orderbook
            orderbook = OrderBook(
                symbol="BTCUSDT",
                timestamp=datetime.now(timezone.utc),
                bids=[PriceLevel(price=49990.0, size=1.0)],
                asks=[PriceLevel(price=50010.0, size=1.0)]
            )
            
            # Create test quotes at different price bins
            our_quotes = {
                "bids": [
                    {"price": 49975.0, "size": 0.5},  # 5 bps from mid
                    {"price": 49950.0, "size": 0.3}   # 10 bps from mid
                ],
                "asks": [
                    {"price": 50025.0, "size": 0.5},  # 5 bps from mid
                    {"price": 50050.0, "size": 0.3}   # 10 bps from mid
                ]
            }
            
            # Record market snapshot
            recorder.record_market_snapshot("BTCUSDT", orderbook, our_quotes, 0.15)
            
            # Check that quotes were binned correctly
            symbol_data = recorder.hourly_data["BTCUSDT"]
            assert len(symbol_data["quotes"]) == 4  # 2 bids + 2 asks
            
            # Count bins
            bin_5_count = sum(1 for q in symbol_data["quotes"] if q["price_bin_bps"] == 5)
            bin_10_count = sum(1 for q in symbol_data["quotes"] if q["price_bin_bps"] == 10)
            
            assert bin_5_count == 2  # 1 bid + 1 ask at 5 bps
            assert bin_10_count == 2  # 1 bid + 1 ask at 10 bps
    
    @pytest.mark.asyncio
    async def test_empty_summary_handling(self):
        """Test handling of empty hourly data."""
        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.storage = MagicMock()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = ResearchRecorder(config, temp_dir)
            
            # Try to generate summary with no data
            test_hour = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
            await recorder._generate_hourly_summaries(test_hour)
            
            # Should not create any files
            summaries_dir = Path(temp_dir) / "summaries"
            if summaries_dir.exists():
                assert len(list(summaries_dir.rglob("*.json"))) == 0
    
    @pytest.mark.asyncio
    async def test_queue_wait_cdf_edge_cases(self):
        """Test queue wait CDF calculation with edge cases."""
        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.storage = MagicMock()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = ResearchRecorder(config, temp_dir)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='test_sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='test_hash'):
                
                symbol = "BTCUSDT"
                test_hour = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
                
                # Test with single queue wait value
                recorder.hourly_data[symbol] = {
                    "orders": [],
                    "quotes": [],
                    "fills": [],
                    "queue_waits": [150.0]
                }
                
                await recorder._generate_hourly_summaries(test_hour)
                
                # Read summary
                summary_path = Path(temp_dir) / "summaries" / symbol / f"{symbol}_2025-01-15_14.json"
                with open(summary_path, 'r') as f:
                    summary = json.load(f)
                
                # All percentiles should be the same value
                cdf = summary["queue_wait_cdf_ms"]
                assert len(cdf) == 4
                for point in cdf:
                    assert point["v"] == 150.0

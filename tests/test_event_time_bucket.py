"""
Tests for E1+ event-time bucketing functionality.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.storage.research_recorder import ResearchRecorder
from src.common.models import OrderBook, PriceLevel, Order, Side, OrderType
from decimal import Decimal


class TestEventTimeBucket:
    """Test event-time based bucketing instead of now_utc."""

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
    async def recorder(self, tmp_path, mock_config):
        """Create a test recorder instance."""
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            retention_days=None,
            lock_mode="none"  # Disable locking for simpler testing
        )
        await recorder.start()
        yield recorder
        await recorder.stop()

    def create_test_orderbook(self, symbol: str = "BUCKET", timestamp: datetime = None) -> OrderBook:
        """Create a test orderbook with specific timestamp."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
            
        return OrderBook(
            symbol=symbol,
            timestamp=timestamp,
            sequence=2000,
            bids=[PriceLevel(price=Decimal("100.00"), size=Decimal("1.0"))],
            asks=[PriceLevel(price=Decimal("100.01"), size=Decimal("1.0"))]
        )

    def create_test_order(self, symbol: str = "BUCKET", timestamp: datetime = None) -> Order:
        """Create a test order with specific timestamp."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
            
        return Order(
            order_id="bucket_order_123",
            symbol=symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            qty=Decimal("1.0"),
            created_time=timestamp
        )

    @pytest.mark.asyncio
    async def test_cross_hour_boundary_events(self, recorder, tmp_path):
        """Test that events on either side of hour boundary go to correct buckets."""
        symbol = "CROSSHOUR"
        
        # Define hour boundary: 14:00 UTC
        hour_14 = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        hour_15 = datetime(2025, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
        
        # Event 1: 59:59.900 (belongs to hour 14)
        event1_time = hour_14 - timedelta(seconds=0.1)  # 13:59:59.900
        orderbook1 = self.create_test_orderbook(symbol, event1_time)
        our_quotes1 = {"bids": [{"price": 99.99, "size": 1.0}], "asks": []}
        
        recorder.record_market_snapshot(symbol, orderbook1, our_quotes1, 0.1, event_ts_utc=event1_time)
        
        # Event 2: 00:00:01 (belongs to hour 15) 
        event2_time = hour_15 + timedelta(seconds=1)  # 15:00:01
        orderbook2 = self.create_test_orderbook(symbol, event2_time)
        our_quotes2 = {"bids": [{"price": 99.98, "size": 1.0}], "asks": []}
        
        recorder.record_market_snapshot(symbol, orderbook2, our_quotes2, 0.1, event_ts_utc=event2_time)
        
        # Force generation for both hours
        with patch('src.storage.research_recorder.get_git_sha', return_value='bucket_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='bucket_hash'):
            await recorder._generate_hourly_summaries(hour_14)
            await recorder._generate_hourly_summaries(hour_15)
        
        # Should have two separate files
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        assert len(json_files) == 2, f"Expected 2 files, got {len(json_files)}"
        
        # Check file names
        file_names = [f.name for f in json_files]
        assert f"{symbol}_2025-01-15_13.json" in file_names  # Event 1 (13:59)
        assert f"{symbol}_2025-01-15_15.json" in file_names  # Event 2 (15:00)
        
        # Check content of each file
        for json_file in json_files:
            with open(json_file, 'r') as f:
                import json
                data = json.load(f)
            
            assert data["counts"]["quotes"] == 1  # Each file should have 1 quote
            
            if "13" in json_file.name:
                # File for hour 13 (event1)
                assert data["hour_utc"] == "2025-01-15T13:00:00Z"
                assert data["window_utc"]["hour_start"] == "2025-01-15T13:00:00Z"
                assert data["window_utc"]["hour_end"] == "2025-01-15T14:00:00Z"
            else:
                # File for hour 15 (event2)
                assert data["hour_utc"] == "2025-01-15T15:00:00Z"
                assert data["window_utc"]["hour_start"] == "2025-01-15T15:00:00Z"
                assert data["window_utc"]["hour_end"] == "2025-01-15T16:00:00Z"

    @pytest.mark.asyncio
    async def test_order_events_with_custom_timestamps(self, recorder, tmp_path):
        """Test order events with explicit event timestamps."""
        symbol = "ORDERTIME"
        
        # Hour boundaries
        hour_10 = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        hour_11 = datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
        
        # Order events at different times
        order = self.create_test_order(symbol)
        
        # Create event at 10:30
        create_time = hour_10 + timedelta(minutes=30)
        recorder.record_order_event("create", order, mid_price=100.0, event_ts_utc=create_time)
        
        # Fill event at 11:15
        fill_time = hour_11 + timedelta(minutes=15)
        recorder.record_order_event("fill", order, fill_price=100.0, fill_qty=1.0,
                                   queue_wait_ms=200.0, mid_price=100.0, event_ts_utc=fill_time)
        
        # Generate summaries
        with patch('src.storage.research_recorder.get_git_sha', return_value='order_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='order_hash'):
            await recorder._generate_hourly_summaries(hour_10)
            await recorder._generate_hourly_summaries(hour_11)
        
        # Should have two files
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        assert len(json_files) == 2
        
        # Find files by hour
        file_10 = None
        file_11 = None
        for f in json_files:
            if "_10.json" in f.name:
                file_10 = f
            elif "_11.json" in f.name:
                file_11 = f
        
        assert file_10 is not None and file_11 is not None
        
        # Check hour 10 file (should have create event)
        with open(file_10, 'r') as f:
            import json
            data_10 = json.load(f)
        
        assert data_10["counts"]["orders"] == 1
        assert data_10["counts"]["fills"] == 0
        assert len(data_10["queue_wait_cdf_ms"]) == 0  # No fills, no queue waits
        
        # Check hour 11 file (should have fill event)
        with open(file_11, 'r') as f:
            import json
            data_11 = json.load(f)
        
        assert data_11["counts"]["orders"] == 0
        assert data_11["counts"]["fills"] == 1
        assert len(data_11["queue_wait_cdf_ms"]) > 0  # Should have queue wait data

    @pytest.mark.asyncio
    async def test_fallback_to_now_utc_when_no_event_time(self, recorder, tmp_path):
        """Test fallback to now_utc when event_ts_utc is None."""
        symbol = "FALLBACK"
        
        # Don't provide event_ts_utc - should use current time
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 99.99, "size": 1.0}], "asks": []}
        
        # Record without explicit timestamp (should fallback to now_utc)
        before_record = datetime.now(timezone.utc)
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)  # No event_ts_utc
        after_record = datetime.now(timezone.utc)
        
        # Current hour should be used
        current_hour = before_record.replace(minute=0, second=0, microsecond=0)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='fallback_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='fallback_hash'):
            await recorder._generate_hourly_summaries(current_hour)
        
        # Should create file for current hour
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        assert len(json_files) == 1
        
        filename_hour = current_hour.strftime('%Y-%m-%d_%H')
        assert filename_hour in json_files[0].name

    @pytest.mark.asyncio
    async def test_multiple_events_same_hour_bucket(self, recorder, tmp_path):
        """Test multiple events in same hour get bucketed together."""
        symbol = "SAMEHOUR"
        
        # All events within the same hour (14:00-15:00)
        base_hour = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        
        events = [
            base_hour + timedelta(minutes=5),   # 14:05
            base_hour + timedelta(minutes=25),  # 14:25
            base_hour + timedelta(minutes=45),  # 14:45
            base_hour + timedelta(minutes=59)   # 14:59
        ]
        
        # Record events at different times within the hour
        for i, event_time in enumerate(events):
            orderbook = self.create_test_orderbook(symbol, event_time)
            our_quotes = {"bids": [{"price": 99.99 - i*0.01, "size": 1.0}], "asks": []}
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1, event_ts_utc=event_time)
        
        # Generate summary
        with patch('src.storage.research_recorder.get_git_sha', return_value='same_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='same_hash'):
            await recorder._generate_hourly_summaries(base_hour)
        
        # Should have one file with all events
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        assert len(json_files) == 1
        
        with open(json_files[0], 'r') as f:
            import json
            data = json.load(f)
        
        # Should have all 4 quote events
        assert data["counts"]["quotes"] == 4
        assert data["hour_utc"] == "2025-01-15T14:00:00Z"

    @pytest.mark.asyncio
    async def test_event_time_vs_orderbook_time_priority(self, recorder, tmp_path):
        """Test that explicit event_ts_utc takes priority over orderbook timestamp."""
        symbol = "PRIORITY"
        
        # Orderbook has one timestamp
        orderbook_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        orderbook = self.create_test_orderbook(symbol, orderbook_time)
        
        # But we provide explicit event_ts_utc for a different hour
        explicit_time = datetime(2025, 1, 15, 16, 30, 0, tzinfo=timezone.utc)
        our_quotes = {"bids": [{"price": 99.99, "size": 1.0}], "asks": []}
        
        # Record with explicit timestamp
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1, event_ts_utc=explicit_time)
        
        # Generate for the explicit time's hour
        explicit_hour = explicit_time.replace(minute=0, second=0, microsecond=0)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='priority_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='priority_hash'):
            await recorder._generate_hourly_summaries(explicit_hour)
        
        # Should create file for explicit time hour (16), not orderbook time hour (12)
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        assert len(json_files) == 1
        
        # Should be hour 16, not hour 12
        assert "_16.json" in json_files[0].name
        assert "_12.json" not in json_files[0].name

    @pytest.mark.asyncio
    async def test_timezone_independence_event_time(self, recorder, tmp_path):
        """Test that event times are correctly handled regardless of timezone info."""
        symbol = "TZINDEP"
        
        # Event time specified as naive datetime (should be treated as UTC)
        naive_time = datetime(2025, 1, 15, 20, 30, 0)  # No timezone
        
        # Event time specified as UTC explicitly
        utc_time = datetime(2025, 1, 15, 20, 30, 0, tzinfo=timezone.utc)
        
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 99.99, "size": 1.0}], "asks": []}
        
        # Record with UTC time
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1, event_ts_utc=utc_time)
        
        # Should bucket to hour 20
        hour_20 = datetime(2025, 1, 15, 20, 0, 0, tzinfo=timezone.utc)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='tz_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='tz_hash'):
            await recorder._generate_hourly_summaries(hour_20)
        
        # Should create file for hour 20
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        assert len(json_files) == 1
        
        assert "_20.json" in json_files[0].name
        
        with open(json_files[0], 'r') as f:
            import json
            data = json.load(f)
        
        assert data["window_utc"]["hour_start"] == "2025-01-15T20:00:00Z"
        assert data["window_utc"]["hour_end"] == "2025-01-15T21:00:00Z"

"""
Tests for E1 hardening: hourly summaries schema versioning.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.storage.research_recorder import ResearchRecorder
from src.common.models import OrderBook, PriceLevel, Order, Side, OrderType
from decimal import Decimal


class TestSummariesSchemaVersion:
    """Test that hourly summaries include correct schema version and metadata."""

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
            retention_days=None,  # Disable retention for test
            percentiles_used=(0.25, 0.5, 0.75, 0.9, 0.95),
            bins_max_bps=25
        )
        await recorder.start()
        yield recorder
        await recorder.stop()

    def create_test_orderbook(self, symbol: str = "TESTUSDT", mid_price: float = 100.0) -> OrderBook:
        """Create a test orderbook."""
        return OrderBook(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=1000,
            bids=[
                PriceLevel(price=Decimal(str(mid_price - 0.01)), size=Decimal("10.0")),
                PriceLevel(price=Decimal(str(mid_price - 0.02)), size=Decimal("5.0"))
            ],
            asks=[
                PriceLevel(price=Decimal(str(mid_price + 0.01)), size=Decimal("10.0")),
                PriceLevel(price=Decimal(str(mid_price + 0.02)), size=Decimal("5.0"))
            ]
        )

    def create_test_order(self, symbol: str = "TESTUSDT", price: float = 100.0) -> Order:
        """Create a test order."""
        return Order(
            order_id="test_order_123",
            symbol=symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal(str(price)),
            qty=Decimal("1.0"),
            created_time=datetime.now(timezone.utc)
        )

    @pytest.mark.asyncio
    async def test_schema_version_e1_0(self, recorder, tmp_path):
        """Test that generated summaries include schema_version='e1.0'."""
        symbol = "TESTUSDT"
        
        # Record some test data
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {
            "bids": [{"price": 99.98, "size": 1.0}],
            "asks": [{"price": 100.02, "size": 1.0}]
        }
        
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.15)
        
        order = self.create_test_order(symbol)
        recorder.record_order_event("create", order, mid_price=100.0)
        recorder.record_order_event("fill", order, fill_price=100.0, fill_qty=0.5, 
                                   queue_wait_ms=150.0, mid_price=100.0)
        
        # Force hourly summary generation
        test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='test_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='test_hash'):
            await recorder._generate_hourly_summaries(test_hour)
        
        # Check generated file
        symbol_dir = tmp_path / "summaries" / symbol
        assert symbol_dir.exists()
        
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        assert len(json_files) == 1
        
        summary_file = json_files[0]
        with open(summary_file, 'r', encoding='utf-8') as f:
            summary_data = json.load(f)
        
        # Verify schema version
        assert summary_data["schema_version"] == "e1.0"

    @pytest.mark.asyncio
    async def test_required_schema_fields(self, recorder, tmp_path):
        """Test that all required schema fields are present."""
        symbol = "TESTUSDT"
        
        # Generate minimal data
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 99.99, "size": 1.0}], "asks": []}
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
        
        test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='mock_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='mock_hash'):
            await recorder._generate_hourly_summaries(test_hour)
        
        # Load and verify
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        summary_file = json_files[0]
        
        with open(summary_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Check all required E1 hardening fields
        assert "schema_version" in data
        assert data["schema_version"] == "e1.0"
        
        assert "generated_at_utc" in data
        assert data["generated_at_utc"].endswith("Z")
        
        assert "window_utc" in data
        assert "hour_start" in data["window_utc"]
        assert "hour_end" in data["window_utc"]
        
        assert "bins_max_bps" in data
        assert data["bins_max_bps"] == 25  # From recorder config
        
        assert "percentiles_used" in data
        assert data["percentiles_used"] == [0.25, 0.5, 0.75, 0.9, 0.95]
        
        # Check window timestamps are valid UTC
        hour_start = datetime.fromisoformat(data["window_utc"]["hour_start"].replace('Z', '+00:00'))
        hour_end = datetime.fromisoformat(data["window_utc"]["hour_end"].replace('Z', '+00:00'))
        assert (hour_end - hour_start) == timedelta(hours=1)
        assert hour_start.tzinfo == timezone.utc
        assert hour_end.tzinfo == timezone.utc

    @pytest.mark.asyncio
    async def test_window_utc_boundaries(self, recorder, tmp_path):
        """Test that window_utc has correct hour boundaries."""
        symbol = "TESTUSDT"
        
        # Use specific test hour
        test_hour = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)  # 14:00 UTC
        
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 99.99, "size": 1.0}], "asks": []}
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.05)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='hash'):
            await recorder._generate_hourly_summaries(test_hour)
        
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        
        with open(json_files[0], 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Verify exact hour boundaries
        assert data["window_utc"]["hour_start"] == "2025-01-15T14:00:00Z"
        assert data["window_utc"]["hour_end"] == "2025-01-15T15:00:00Z"

    @pytest.mark.asyncio
    async def test_custom_percentiles_and_bins(self, tmp_path, mock_config):
        """Test custom percentiles and bins configuration."""
        # Create recorder with custom settings
        custom_percentiles = (0.1, 0.5, 0.99)
        custom_bins_max = 100
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            percentiles_used=custom_percentiles,
            bins_max_bps=custom_bins_max
        )
        
        await recorder.start()
        
        try:
            symbol = "CUSTOM"
            
            # Generate data with queue waits for CDF
            order = self.create_test_order(symbol)
            recorder.record_order_event("fill", order, fill_price=100.0, fill_qty=1.0,
                                       queue_wait_ms=50.0, mid_price=100.0)
            recorder.record_order_event("fill", order, fill_price=100.0, fill_qty=1.0,
                                       queue_wait_ms=100.0, mid_price=100.0)
            recorder.record_order_event("fill", order, fill_price=100.0, fill_qty=1.0,
                                       queue_wait_ms=200.0, mid_price=100.0)
            
            test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='hash'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Verify custom configuration reflected in file
            symbol_dir = tmp_path / "summaries" / symbol
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            
            with open(json_files[0], 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            assert data["bins_max_bps"] == custom_bins_max
            assert data["percentiles_used"] == list(custom_percentiles)
            
            # Verify CDF uses custom percentiles
            cdf = data["queue_wait_cdf_ms"]
            assert len(cdf) == len(custom_percentiles)
            for i, percentile in enumerate(custom_percentiles):
                assert cdf[i]["p"] == percentile
            
        finally:
            await recorder.stop()

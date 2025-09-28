"""
Tests for E1 hardening: idempotency with overwrite and merge strategies.
"""

import json
import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.storage.research_recorder import ResearchRecorder
from src.common.models import OrderBook, PriceLevel, Order, Side, OrderType
from decimal import Decimal


class TestIdempotencyOverwriteMerge:
    """Test idempotency with overwrite and merge strategies."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = MagicMock()
        config.storage = MagicMock()
        config.storage.compress = 'none'
        config.storage.batch_size = 100
        config.storage.flush_ms = 50
        return config

    def create_test_orderbook(self, symbol: str = "IDEM", mid_price: float = 200.0) -> OrderBook:
        """Create a test orderbook."""
        return OrderBook(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=4000,
            bids=[PriceLevel(price=Decimal(str(mid_price - 0.01)), size=Decimal("2.0"))],
            asks=[PriceLevel(price=Decimal(str(mid_price + 0.01)), size=Decimal("2.0"))]
        )

    def create_test_order(self, symbol: str = "IDEM", price: float = 200.0) -> Order:
        """Create a test order."""
        return Order(
            order_id="idem_order_456",
            symbol=symbol,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal(str(price)),
            qty=Decimal("0.5"),
            created_time=datetime.now(timezone.utc)
        )

    @pytest.mark.asyncio
    async def test_overwrite_existing_hour_default(self, tmp_path, mock_config):
        """Test that overwrite_existing_hour=True replaces files by default."""
        symbol = "IDEM"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            overwrite_existing_hour=True,  # Default behavior
            retention_days=None
        )
        
        await recorder.start()
        
        try:
            test_hour = datetime(2025, 1, 15, 16, 0, 0, tzinfo=timezone.utc)
            
            # First write - generate data and write summary
            orderbook = self.create_test_orderbook(symbol)
            our_quotes = {"bids": [{"price": 199.99, "size": 1.0}], "asks": []}
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
            
            order = self.create_test_order(symbol)
            recorder.record_order_event("create", order, mid_price=200.0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='first_sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='first_hash'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Get first file content and modification time
            symbol_dir = tmp_path / "summaries" / symbol
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 1
            
            first_file = json_files[0]
            first_mtime = first_file.stat().st_mtime
            
            with open(first_file, 'r') as f:
                first_content = json.load(f)
            
            # Verify first content
            assert first_content["counts"]["orders"] == 1
            assert first_content["metadata"]["git_sha"] == "first_sha"
            
            # Small delay to ensure different modification time
            time.sleep(0.1)
            
            # Second write to same hour - should overwrite
            order2 = self.create_test_order(symbol, price=200.5)
            recorder.record_order_event("create", order2, mid_price=200.0)
            recorder.record_order_event("fill", order2, fill_price=200.5, fill_qty=0.5,
                                       queue_wait_ms=100.0, mid_price=200.0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='second_sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='second_hash'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Should still be only one file
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 1
            
            second_file = json_files[0]
            second_mtime = second_file.stat().st_mtime
            
            with open(second_file, 'r') as f:
                second_content = json.load(f)
            
            # File should be replaced (different mtime and content)
            assert second_mtime > first_mtime
            assert second_content["counts"]["orders"] == 1  # Only second write data
            assert second_content["counts"]["fills"] == 1
            assert second_content["metadata"]["git_sha"] == "second_sha"
            
            # Generated_at_utc should be different
            assert second_content["generated_at_utc"] != first_content["generated_at_utc"]
            
        finally:
            await recorder.stop()

    @pytest.mark.asyncio
    async def test_merge_strategy_sum_bins(self, tmp_path, mock_config):
        """Test merge_strategy='sum_bins' combines data correctly."""
        symbol = "MERGE"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            overwrite_existing_hour=False,
            merge_strategy="sum_bins",
            retention_days=None
        )
        
        await recorder.start()
        
        try:
            test_hour = datetime(2025, 1, 15, 17, 0, 0, tzinfo=timezone.utc)
            
            # First write - bid quotes at 199.9 (bin 5)
            orderbook = self.create_test_orderbook(symbol)
            our_quotes = {"bids": [{"price": 199.9, "size": 2.0}], "asks": []}  # 5 bps from mid
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.05)
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.05)  # 2 quotes
            
            order1 = self.create_test_order(symbol, price=199.9)
            recorder.record_order_event("create", order1, mid_price=200.0)
            recorder.record_order_event("fill", order1, fill_price=199.9, fill_qty=0.2,
                                       queue_wait_ms=50.0, mid_price=200.0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='merge_sha_1'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='merge_hash_1'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Verify first file content
            symbol_dir = tmp_path / "summaries" / symbol
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 1
            
            with open(json_files[0], 'r') as f:
                first_data = json.load(f)
            
            assert first_data["counts"]["orders"] == 1
            assert first_data["counts"]["quotes"] == 2
            assert first_data["counts"]["fills"] == 1
            assert "5" in first_data["hit_rate_by_bin"]  # 5 bps bin
            assert first_data["hit_rate_by_bin"]["5"]["count"] == 2  # 2 quotes
            assert first_data["hit_rate_by_bin"]["5"]["fills"] == 1  # 1 fill
            
            # Second write to same hour - ask quotes at 200.2 (bin 10)
            our_quotes_2 = {"bids": [], "asks": [{"price": 200.2, "size": 1.0}]}  # 10 bps from mid
            recorder.record_market_snapshot(symbol, orderbook, our_quotes_2, 0.05)
            recorder.record_market_snapshot(symbol, orderbook, our_quotes_2, 0.05)
            recorder.record_market_snapshot(symbol, orderbook, our_quotes_2, 0.05)  # 3 more quotes
            
            order2 = self.create_test_order(symbol, price=200.2)
            recorder.record_order_event("create", order2, mid_price=200.0)
            recorder.record_order_event("create", order2, mid_price=200.0)  # 2 more orders
            recorder.record_order_event("fill", order2, fill_price=200.2, fill_qty=0.3,
                                       queue_wait_ms=75.0, mid_price=200.0)
            recorder.record_order_event("fill", order2, fill_price=200.2, fill_qty=0.2,
                                       queue_wait_ms=125.0, mid_price=200.0)  # 2 more fills
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='merge_sha_2'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='merge_hash_2'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Should still be only one file
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 1
            
            with open(json_files[0], 'r') as f:
                merged_data = json.load(f)
            
            # Counts should be summed
            assert merged_data["counts"]["orders"] == 3  # 1 + 2
            assert merged_data["counts"]["quotes"] == 5  # 2 + 3
            assert merged_data["counts"]["fills"] == 3   # 1 + 2
            
            # Bins should be merged
            assert "5" in merged_data["hit_rate_by_bin"]
            assert "10" in merged_data["hit_rate_by_bin"]
            
            # Bin 5 (from first write)
            assert merged_data["hit_rate_by_bin"]["5"]["count"] == 2
            assert merged_data["hit_rate_by_bin"]["5"]["fills"] == 1
            
            # Bin 10 (from second write)
            assert merged_data["hit_rate_by_bin"]["10"]["count"] == 3
            assert merged_data["hit_rate_by_bin"]["10"]["fills"] == 2
            
            # CDF should be from the latest (second) write with wait times [75.0, 125.0]
            cdf = merged_data["queue_wait_cdf_ms"]
            assert len(cdf) > 0
            # Since we have 3 total wait times [50.0, 75.0, 125.0], CDF should reflect newer data
            
            # Metadata should be from the latest write
            assert merged_data["metadata"]["git_sha"] == "merge_sha_2"
            
        finally:
            await recorder.stop()

    @pytest.mark.asyncio
    async def test_no_overwrite_no_merge_skips(self, tmp_path, mock_config, caplog):
        """Test that overwrite=False and merge_strategy=None skips existing files."""
        symbol = "SKIP"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            overwrite_existing_hour=False,
            merge_strategy=None,
            retention_days=None
        )
        
        await recorder.start()
        
        try:
            test_hour = datetime(2025, 1, 15, 18, 0, 0, tzinfo=timezone.utc)
            
            # First write
            orderbook = self.create_test_orderbook(symbol)
            our_quotes = {"bids": [{"price": 199.99, "size": 1.0}], "asks": []}
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='skip_sha_1'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='skip_hash_1'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Get original content and mtime
            symbol_dir = tmp_path / "summaries" / symbol
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 1
            
            original_file = json_files[0]
            original_mtime = original_file.stat().st_mtime
            
            with open(original_file, 'r') as f:
                original_content = json.load(f)
            
            time.sleep(0.1)  # Ensure different timestamp
            
            # Second write to same hour - should be skipped
            order = self.create_test_order(symbol)
            recorder.record_order_event("create", order, mid_price=200.0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='skip_sha_2'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='skip_hash_2'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # File should be unchanged
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 1
            
            unchanged_file = json_files[0]
            unchanged_mtime = unchanged_file.stat().st_mtime
            
            with open(unchanged_file, 'r') as f:
                unchanged_content = json.load(f)
            
            # File should be exactly the same
            assert unchanged_mtime == original_mtime
            assert unchanged_content == original_content
            assert unchanged_content["metadata"]["git_sha"] == "skip_sha_1"  # Original SHA
            
            # Should have logged a skip message
            assert "Summary exists, skipping" in caplog.text
            
        finally:
            await recorder.stop()

    @pytest.mark.asyncio
    async def test_merge_preserves_latest_cdf(self, tmp_path, mock_config):
        """Test that merge strategy keeps the latest CDF data."""
        symbol = "CDF"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            overwrite_existing_hour=False,
            merge_strategy="sum_bins",
            percentiles_used=(0.5, 0.9),  # Simplified for testing
            retention_days=None
        )
        
        await recorder.start()
        
        try:
            test_hour = datetime(2025, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
            
            # First write with queue wait times [100, 200, 300]
            order1 = self.create_test_order(symbol)
            recorder.record_order_event("fill", order1, fill_price=200.0, fill_qty=0.5,
                                       queue_wait_ms=100.0, mid_price=200.0)
            recorder.record_order_event("fill", order1, fill_price=200.0, fill_qty=0.3,
                                       queue_wait_ms=200.0, mid_price=200.0)
            recorder.record_order_event("fill", order1, fill_price=200.0, fill_qty=0.2,
                                       queue_wait_ms=300.0, mid_price=200.0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='cdf_sha_1'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='cdf_hash_1'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Get first CDF
            symbol_dir = tmp_path / "summaries" / symbol
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            
            with open(json_files[0], 'r') as f:
                first_data = json.load(f)
            
            first_cdf = first_data["queue_wait_cdf_ms"]
            # CDF for [100, 200, 300]: p=0.5 -> 200, p=0.9 -> 300
            assert len(first_cdf) == 2
            assert first_cdf[0]["p"] == 0.5
            assert first_cdf[1]["p"] == 0.9
            
            # Second write with different queue wait times [50, 400]
            order2 = self.create_test_order(symbol)
            recorder.record_order_event("fill", order2, fill_price=200.0, fill_qty=0.4,
                                       queue_wait_ms=50.0, mid_price=200.0)
            recorder.record_order_event("fill", order2, fill_price=200.0, fill_qty=0.6,
                                       queue_wait_ms=400.0, mid_price=200.0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='cdf_sha_2'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='cdf_hash_2'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Load merged data
            with open(json_files[0], 'r') as f:
                merged_data = json.load(f)
            
            # Fill counts should be merged (3 + 2 = 5)
            assert merged_data["counts"]["fills"] == 5
            
            # But CDF should be from the latest write only [50, 400]
            merged_cdf = merged_data["queue_wait_cdf_ms"]
            assert len(merged_cdf) == 2
            
            # CDF for [50, 400]: p=0.5 -> 50, p=0.9 -> 400 (since only 2 values)
            cdf_values = [entry["v"] for entry in merged_cdf]
            assert 50.0 in cdf_values  # Latest data
            assert 400.0 in cdf_values  # Latest data
            # Should NOT contain values from first write (100, 200, 300)
            assert not any(v in [100.0, 200.0, 300.0] for v in cdf_values)
            
        finally:
            await recorder.stop()

    @pytest.mark.asyncio
    async def test_idempotent_filename_consistency(self, tmp_path, mock_config):
        """Test that repeated writes to same hour use consistent filenames."""
        symbol = "FNAME"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            overwrite_existing_hour=True
        )
        
        await recorder.start()
        
        try:
            # Use specific hour for predictable filename
            test_hour = datetime(2025, 1, 15, 20, 0, 0, tzinfo=timezone.utc)
            expected_filename = f"{symbol}_2025-01-15_20.json"
            
            # First write
            orderbook = self.create_test_orderbook(symbol)
            our_quotes = {"bids": [{"price": 199.99, "size": 1.0}], "asks": []}
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='fname_sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='fname_hash'):
                await recorder._generate_hourly_summaries(test_hour)
            
            symbol_dir = tmp_path / "summaries" / symbol
            json_files = list(symbol_dir.glob("*.json"))
            assert len(json_files) == 1
            assert json_files[0].name == expected_filename
            
            # Second write to same hour
            order = self.create_test_order(symbol)
            recorder.record_order_event("create", order, mid_price=200.0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='fname_sha_2'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='fname_hash_2'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Should still be same filename
            json_files = list(symbol_dir.glob("*.json"))
            assert len(json_files) == 1
            assert json_files[0].name == expected_filename
            
        finally:
            await recorder.stop()

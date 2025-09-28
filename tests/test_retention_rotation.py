"""
Tests for E1 hardening: file retention and rotation.
"""

import json
import os
import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.storage.research_recorder import ResearchRecorder
from src.common.models import OrderBook, PriceLevel
from decimal import Decimal


class TestRetentionRotation:
    """Test file retention and rotation functionality."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = MagicMock()
        config.storage = MagicMock()
        config.storage.compress = 'none'
        config.storage.batch_size = 100
        config.storage.flush_ms = 50
        return config

    def create_test_orderbook(self, symbol: str = "RETN", mid_price: float = 75.0) -> OrderBook:
        """Create a test orderbook."""
        return OrderBook(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=3000,
            bids=[PriceLevel(price=Decimal(str(mid_price - 0.01)), size=Decimal("3.0"))],
            asks=[PriceLevel(price=Decimal(str(mid_price + 0.01)), size=Decimal("3.0"))]
        )

    def create_old_summary_files(self, symbol_dir: Path, symbol: str, days_back: int = 30):
        """Create mock summary files with various ages."""
        files_created = []
        base_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        for days_ago in range(days_back):
            for hour in [0, 12]:  # Two files per day
                file_time = base_time - timedelta(days=days_ago, hours=hour)
                filename = f"{symbol}_{file_time.strftime('%Y-%m-%d_%H')}.json"
                file_path = symbol_dir / filename
                
                # Create file with basic content
                mock_data = {
                    "symbol": symbol,
                    "hour_utc": file_time.isoformat() + "Z",
                    "counts": {"orders": 1, "quotes": 1, "fills": 0},
                    "hit_rate_by_bin": {},
                    "queue_wait_cdf_ms": [],
                    "metadata": {"git_sha": "old", "cfg_hash": "old"}
                }
                
                with open(file_path, 'w') as f:
                    json.dump(mock_data, f)
                
                # Set file modification time to match the content timestamp
                mod_time = file_time.timestamp()
                os.utime(file_path, (mod_time, mod_time))
                
                files_created.append((filename, file_time))
        
        return files_created

    @pytest.mark.asyncio
    async def test_ttl_retention_removes_old_files(self, tmp_path, mock_config):
        """Test that files older than retention_days are removed."""
        symbol = "RETN"
        retention_days = 7
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            retention_days=retention_days,
            keep_last=None
        )
        
        # Create symbol directory and old files
        symbol_dir = tmp_path / "summaries" / symbol
        symbol_dir.mkdir(parents=True)
        
        files_created = self.create_old_summary_files(symbol_dir, symbol, days_back=20)
        
        # All files should exist initially
        assert len(list(symbol_dir.glob("*.json"))) == 40  # 20 days * 2 files/day
        
        # Run pruning
        recorder._prune_summaries(symbol)
        
        # Check which files remain
        remaining_files = list(symbol_dir.glob("*.json"))
        remaining_count = len(remaining_files)
        
        # Should keep files from last 7 days (7 * 2 = 14 files)
        # Plus potentially today's files
        assert remaining_count <= 16  # Allow some margin for timing
        assert remaining_count >= 14
        
        # Verify that remaining files are recent
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        for file_path in remaining_files:
            file_time = recorder._parse_utc_from_filename(file_path.name)
            assert file_time >= cutoff, f"File {file_path.name} is older than cutoff"

    @pytest.mark.asyncio
    async def test_keep_last_overrides_ttl(self, tmp_path, mock_config):
        """Test that keep_last takes priority over TTL retention."""
        symbol = "RETN"
        keep_last = 5
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            retention_days=30,  # Generous TTL
            keep_last=keep_last
        )
        
        # Create symbol directory and many old files
        symbol_dir = tmp_path / "summaries" / symbol
        symbol_dir.mkdir(parents=True)
        
        self.create_old_summary_files(symbol_dir, symbol, days_back=15)
        
        # Should have 30 files initially (15 days * 2 files/day)
        assert len(list(symbol_dir.glob("*.json"))) == 30
        
        # Run pruning
        recorder._prune_summaries(symbol)
        
        # Should keep exactly 5 files (newest by mtime)
        remaining_files = list(symbol_dir.glob("*.json"))
        assert len(remaining_files) == keep_last
        
        # Verify the 5 remaining files are the newest by modification time
        file_mtimes = [(f, f.stat().st_mtime) for f in remaining_files]
        file_mtimes.sort(key=lambda x: x[1], reverse=True)
        
        # All 5 should be from recent days
        newest_mtime = file_mtimes[0][1]
        oldest_kept_mtime = file_mtimes[-1][1]
        
        # Time difference between newest and oldest kept should be small
        time_diff = newest_mtime - oldest_kept_mtime
        assert time_diff <= 3 * 24 * 3600  # At most 3 days difference

    @pytest.mark.asyncio
    async def test_retention_with_no_files(self, tmp_path, mock_config):
        """Test that pruning works correctly when no files exist."""
        symbol = "EMPTY"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            retention_days=7,
            keep_last=10
        )
        
        # Symbol directory doesn't exist
        recorder._prune_summaries(symbol)  # Should not crash
        
        # Create empty symbol directory
        symbol_dir = tmp_path / "summaries" / symbol
        symbol_dir.mkdir(parents=True)
        
        recorder._prune_summaries(symbol)  # Should not crash
        
        # Directory should still exist but be empty
        assert symbol_dir.exists()
        assert len(list(symbol_dir.glob("*.json"))) == 0

    @pytest.mark.asyncio
    async def test_retention_disabled_no_cleanup(self, tmp_path, mock_config):
        """Test that setting retention_days=None and keep_last=None disables cleanup."""
        symbol = "NODROP"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            retention_days=None,
            keep_last=None
        )
        
        # Create symbol directory and old files
        symbol_dir = tmp_path / "summaries" / symbol
        symbol_dir.mkdir(parents=True)
        
        files_created = self.create_old_summary_files(symbol_dir, symbol, days_back=50)
        initial_count = len(list(symbol_dir.glob("*.json")))
        
        # Run pruning - should not remove anything
        recorder._prune_summaries(symbol)
        
        # All files should still exist
        remaining_count = len(list(symbol_dir.glob("*.json")))
        assert remaining_count == initial_count

    @pytest.mark.asyncio
    async def test_pruning_called_after_summary_write(self, tmp_path, mock_config):
        """Test that pruning is automatically called after writing summaries."""
        symbol = "AUTO"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            retention_days=5,
            keep_last=None
        )
        
        await recorder.start()
        
        try:
            # Create some old files manually
            symbol_dir = tmp_path / "summaries" / symbol
            symbol_dir.mkdir(parents=True)
            self.create_old_summary_files(symbol_dir, symbol, days_back=10)
            
            initial_count = len(list(symbol_dir.glob("*.json")))
            assert initial_count == 20  # 10 days * 2 files/day
            
            # Generate new summary which should trigger pruning
            orderbook = self.create_test_orderbook(symbol)
            our_quotes = {"bids": [{"price": 74.99, "size": 1.0}], "asks": []}
            recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
            
            test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='auto_sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='auto_hash'):
                await recorder._generate_hourly_summaries(test_hour)
            
            # Should now have fewer files due to automatic pruning
            final_count = len(list(symbol_dir.glob("*.json")))
            assert final_count < initial_count
            assert final_count <= 11  # 5 days * 2 + new file + margin
            
        finally:
            await recorder.stop()

    def test_parse_utc_from_filename(self, mock_config):
        """Test UTC timestamp parsing from filenames."""
        recorder = ResearchRecorder(
            mock_config,
            "dummy",
            summaries_dir="dummy"
        )
        
        # Valid filenames
        assert recorder._parse_utc_from_filename("BTCUSDT_2025-01-15_14.json") == \
               datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        
        assert recorder._parse_utc_from_filename("TEST_2024-12-31_23.json") == \
               datetime(2024, 12, 31, 23, 0, 0, tzinfo=timezone.utc)
        
        # Complex symbol names
        assert recorder._parse_utc_from_filename("BTC_USDT_PERP_2025-01-01_00.json") == \
               datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        # Invalid filenames should return None
        assert recorder._parse_utc_from_filename("invalid.json") is None
        assert recorder._parse_utc_from_filename("SYMBOL_invalid_time.json") is None
        assert recorder._parse_utc_from_filename("not_json.txt") is None
        assert recorder._parse_utc_from_filename("SYMBOL_2025-01-01.json") is None  # Missing hour

    @pytest.mark.asyncio
    async def test_safe_remove_error_handling(self, tmp_path, mock_config, caplog):
        """Test that file removal errors are handled gracefully."""
        symbol = "SAFE"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            retention_days=1
        )
        
        # Create symbol directory and a file
        symbol_dir = tmp_path / "summaries" / symbol
        symbol_dir.mkdir(parents=True)
        
        test_file = symbol_dir / "SAFE_2024-01-01_00.json"
        test_file.write_text('{"test": "data"}')
        
        # Make file read-only to simulate removal failure
        test_file.chmod(0o444)
        
        # Try to remove - should log warning but not crash
        recorder._safe_remove(test_file)
        
        # On Windows, read-only files can often still be deleted, so check if file exists
        # If it still exists, there should be a warning log
        if test_file.exists():
            assert "Failed to remove" in caplog.text

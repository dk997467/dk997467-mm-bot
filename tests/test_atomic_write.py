"""
Tests for E1 hardening: atomic file writing.
"""

import json
import os
import pytest
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

from src.storage.research_recorder import ResearchRecorder
from src.common.models import OrderBook, PriceLevel
from decimal import Decimal


class TestAtomicWrite:
    """Test atomic file writing functionality."""

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
            retention_days=None
        )
        await recorder.start()
        yield recorder
        await recorder.stop()

    def create_test_orderbook(self, symbol: str = "ATOM", mid_price: float = 50.0) -> OrderBook:
        """Create a test orderbook."""
        return OrderBook(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=2000,
            bids=[PriceLevel(price=Decimal(str(mid_price - 0.01)), size=Decimal("5.0"))],
            asks=[PriceLevel(price=Decimal(str(mid_price + 0.01)), size=Decimal("5.0"))]
        )

    @pytest.mark.asyncio
    async def test_no_tmp_files_after_completion(self, recorder, tmp_path):
        """Test that no .tmp. files remain after successful write."""
        symbol = "ATOM"
        
        # Generate test data
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 49.99, "size": 2.0}], "asks": []}
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
        
        test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='atomic_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='atomic_hash'):
            await recorder._generate_hourly_summaries(test_hour)
        
        # Check that summary was created
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        assert len(json_files) == 1
        
        # Verify no temporary files exist anywhere in the summaries tree
        all_files = list((tmp_path / "summaries").rglob("*"))
        tmp_files = [f for f in all_files if f.is_file() and ".tmp." in f.name]
        assert len(tmp_files) == 0, f"Found temporary files: {tmp_files}"

    @pytest.mark.asyncio
    async def test_atomic_write_with_exception_cleanup(self, recorder, tmp_path):
        """Test that temporary files are cleaned up when write fails."""
        symbol = "ATOM"
        
        # Generate minimal data
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 50.0, "size": 1.0}], "asks": []}
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.05)
        
        test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        # Mock json.dump to raise an exception during write
        original_atomic_write = recorder._atomic_write_json
        
        def failing_atomic_write(path, obj):
            # Call original method but patch json.dump to fail
            with patch('json.dump', side_effect=ValueError("Simulated write failure")):
                try:
                    original_atomic_write(path, obj)
                except ValueError:
                    pass  # Expected to fail
        
        # Patch the atomic write method
        recorder._atomic_write_json = failing_atomic_write
        
        with patch('src.storage.research_recorder.get_git_sha', return_value='fail_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='fail_hash'):
            await recorder._generate_hourly_summaries(test_hour)
        
        # Verify no temporary files were left behind
        all_files = list((tmp_path / "summaries").rglob("*"))
        tmp_files = [f for f in all_files if f.is_file() and ".tmp." in f.name]
        assert len(tmp_files) == 0, f"Temporary files not cleaned up: {tmp_files}"
        
        # Verify main summary file was not created due to failure
        symbol_dir = tmp_path / "summaries" / symbol
        if symbol_dir.exists():
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 0, "Summary file should not exist after write failure"

    def test_atomic_write_json_direct(self, tmp_path, mock_config):
        """Test the _atomic_write_json method directly."""
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            round_dp=3
        )
        
        # Test data with floating point numbers
        test_data = {
            "test_float": 123.456789,
            "nested": {
                "another_float": 987.654321
            },
            "array": [1.111111, 2.222222]
        }
        
        target_file = tmp_path / "test_atomic.json"
        
        # Call atomic write
        recorder._atomic_write_json(target_file, test_data)
        
        # Verify file exists and contains expected data
        assert target_file.exists()
        
        with open(target_file, 'r', encoding='utf-8') as f:
            written_data = json.load(f)
        
        # Verify rounding was applied (round_dp=3)
        assert written_data["test_float"] == 123.457  # Rounded to 3 decimal places
        assert written_data["nested"]["another_float"] == 987.654
        
        # Verify JSON is properly formatted (sorted keys, proper encoding)
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Should be formatted JSON with indentation
        assert '"test_float"' in content
        assert content.count('\n') > 1  # Multi-line due to indent=2

    def test_atomic_write_ensures_directory_creation(self, tmp_path, mock_config):
        """Test that atomic write creates parent directories."""
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries")
        )
        
        # Target file in nested directories that don't exist yet
        deep_path = tmp_path / "deep" / "nested" / "dirs" / "test.json"
        
        test_data = {"created": "directories"}
        
        # Should create all parent directories
        recorder._atomic_write_json(deep_path, test_data)
        
        assert deep_path.exists()
        assert deep_path.parent.is_dir()
        
        with open(deep_path, 'r') as f:
            data = json.load(f)
        assert data["created"] == "directories"

    def test_atomic_write_unique_temp_names(self, tmp_path, mock_config):
        """Test that multiple concurrent writes use unique temp file names."""
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries")
        )
        
        target_file = tmp_path / "test.json"
        temp_names_seen = set()
        
        original_open = open
        
        def tracking_open(filename, mode='r', **kwargs):
            """Track temporary filenames being created."""
            if hasattr(filename, '__fspath__'):
                filename = os.fspath(filename)
            if isinstance(filename, str) and ".tmp." in filename:
                temp_names_seen.add(Path(filename).name)
            return original_open(filename, mode, **kwargs)
        
        # Simulate multiple "concurrent" writes
        with patch('builtins.open', side_effect=tracking_open):
            for i in range(5):
                test_data = {"iteration": i}
                recorder._atomic_write_json(target_file, test_data)
        
        # Each write should have used a unique temporary filename
        assert len(temp_names_seen) == 5
        
        # Verify all temp names have expected format: .tmp.{pid}.{hex}
        for temp_name in temp_names_seen:
            parts = temp_name.split('.')
            assert len(parts) >= 4  # original_name.tmp.{pid}.{hex}
            assert parts[-3] == "tmp"
            assert parts[-2] == str(os.getpid())
            # parts[-1] should be hex string
            try:
                int(parts[-1], 16)
            except ValueError:
                pytest.fail(f"Temp name doesn't end with hex: {temp_name}")

    @pytest.mark.asyncio
    async def test_fsync_error_handling(self, recorder, tmp_path):
        """Test that fsync errors don't prevent file creation."""
        symbol = "FSYNC"
        
        orderbook = self.create_test_orderbook(symbol)
        our_quotes = {"bids": [{"price": 50.0, "size": 1.0}], "asks": []}
        recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
        
        test_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        # Mock os.fsync to raise an exception
        with patch('os.fsync', side_effect=OSError("Fsync not available")), \
             patch('src.storage.research_recorder.get_git_sha', return_value='fsync_sha'), \
             patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='fsync_hash'):
            # Should not raise exception, file should still be created
            await recorder._generate_hourly_summaries(test_hour)
        
        # Verify file was created despite fsync failure
        symbol_dir = tmp_path / "summaries" / symbol
        json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
        assert len(json_files) == 1
        
        # File should contain valid JSON
        with open(json_files[0], 'r') as f:
            data = json.load(f)
        assert data["symbol"] == symbol

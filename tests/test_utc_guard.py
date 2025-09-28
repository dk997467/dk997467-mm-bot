"""
Tests for E1 hardening: UTC timezone guard.
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


class TestUTCGuard:
    """Test UTC timezone independence."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = MagicMock()
        config.storage = MagicMock()
        config.storage.compress = 'none'
        config.storage.batch_size = 100
        config.storage.flush_ms = 50
        return config

    def create_test_orderbook(self, symbol: str = "UTCTEST", mid_price: float = 150.0) -> OrderBook:
        """Create a test orderbook."""
        return OrderBook(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=5000,
            bids=[PriceLevel(price=Decimal(str(mid_price - 0.01)), size=Decimal("1.5"))],
            asks=[PriceLevel(price=Decimal(str(mid_price + 0.01)), size=Decimal("1.5"))]
        )

    @pytest.mark.asyncio
    async def test_utc_independence_berlin_timezone(self, tmp_path, mock_config):
        """Test that summaries use UTC regardless of local timezone (Europe/Berlin)."""
        symbol = "UTCTEST"
        
        # Save original timezone
        original_tz = os.environ.get('TZ')
        
        try:
            # Set local timezone to Europe/Berlin (UTC+1 or UTC+2)
            os.environ['TZ'] = 'Europe/Berlin'
            
            # Try to apply timezone change (not available on all platforms)
            try:
                time.tzset()
            except AttributeError:
                pytest.skip("time.tzset() not available on this platform")
            
            recorder = ResearchRecorder(
                mock_config,
                str(tmp_path / "research"),
                summaries_dir=str(tmp_path / "summaries"),
                retention_days=None
            )
            
            await recorder.start()
            
            try:
                # Use a specific UTC time for testing
                utc_test_time = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
                
                # In Berlin time, this would be 15:00 (UTC+1) or 16:00 (UTC+2)
                # But our files should still use UTC hour 14
                
                orderbook = self.create_test_orderbook(symbol)
                our_quotes = {"bids": [{"price": 149.99, "size": 1.0}], "asks": []}
                recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
                
                with patch('src.storage.research_recorder.get_git_sha', return_value='utc_sha'), \
                     patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='utc_hash'):
                    await recorder._generate_hourly_summaries(utc_test_time)
                
                # Check filename uses UTC hour
                symbol_dir = tmp_path / "summaries" / symbol
                json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
                assert len(json_files) == 1
                
                filename = json_files[0].name
                expected_filename = f"{symbol}_2025-01-15_14.json"  # UTC hour 14, not Berlin local hour
                assert filename == expected_filename
                
                # Check file content has UTC timestamps
                with open(json_files[0], 'r') as f:
                    data = json.load(f)
                
                # window_utc should have UTC times
                assert data["window_utc"]["hour_start"] == "2025-01-15T14:00:00Z"
                assert data["window_utc"]["hour_end"] == "2025-01-15T15:00:00Z"
                
                # hour_utc should be UTC
                assert data["hour_utc"] == "2025-01-15T14:00:00Z"
                
                # generated_at_utc should end with Z (UTC)
                assert data["generated_at_utc"].endswith("Z")
                
                # Parse generated_at_utc to verify it's actually UTC
                generated_time = datetime.fromisoformat(data["generated_at_utc"].replace('Z', '+00:00'))
                assert generated_time.tzinfo == timezone.utc
                
            finally:
                await recorder.stop()
                
        finally:
            # Restore original timezone
            if original_tz is not None:
                os.environ['TZ'] = original_tz
            else:
                os.environ.pop('TZ', None)
            
            try:
                time.tzset()
            except AttributeError:
                pass

    @pytest.mark.asyncio 
    async def test_utc_consistency_across_timezones(self, tmp_path, mock_config):
        """Test that the same UTC time produces identical files regardless of local timezone."""
        symbol = "CONSISTENT"
        
        # Test with specific UTC moment
        utc_moment = datetime(2025, 1, 15, 22, 0, 0, tzinfo=timezone.utc)
        
        # First run: no timezone override (system default)
        recorder1 = ResearchRecorder(
            mock_config,
            str(tmp_path / "research1"),
            summaries_dir=str(tmp_path / "summaries1"),
            retention_days=None
        )
        
        await recorder1.start()
        
        try:
            orderbook = self.create_test_orderbook(symbol)
            our_quotes = {"bids": [{"price": 149.98, "size": 1.0}], "asks": []}
            recorder1.record_market_snapshot(symbol, orderbook, our_quotes, 0.05)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='consistent_sha'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='consistent_hash'):
                await recorder1._generate_hourly_summaries(utc_moment)
        finally:
            await recorder1.stop()
        
        # Second run: simulate different timezone
        original_tz = os.environ.get('TZ')
        
        try:
            os.environ['TZ'] = 'US/Pacific'  # UTC-8 or UTC-7
            try:
                time.tzset()
            except AttributeError:
                pass
            
            recorder2 = ResearchRecorder(
                mock_config,
                str(tmp_path / "research2"),
                summaries_dir=str(tmp_path / "summaries2"),
                retention_days=None
            )
            
            await recorder2.start()
            
            try:
                # Same data, same UTC time
                orderbook = self.create_test_orderbook(symbol)
                our_quotes = {"bids": [{"price": 149.98, "size": 1.0}], "asks": []}
                recorder2.record_market_snapshot(symbol, orderbook, our_quotes, 0.05)
                
                with patch('src.storage.research_recorder.get_git_sha', return_value='consistent_sha'), \
                     patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='consistent_hash'):
                    await recorder2._generate_hourly_summaries(utc_moment)
            finally:
                await recorder2.stop()
                
        finally:
            # Restore timezone
            if original_tz is not None:
                os.environ['TZ'] = original_tz
            else:
                os.environ.pop('TZ', None)
            try:
                time.tzset()
            except AttributeError:
                pass
        
        # Compare the generated files
        file1 = list((tmp_path / "summaries1" / symbol).glob(f"{symbol}_*.json"))[0]
        file2 = list((tmp_path / "summaries2" / symbol).glob(f"{symbol}_*.json"))[0]
        
        # Filenames should be identical
        assert file1.name == file2.name
        assert file1.name == f"{symbol}_2025-01-15_22.json"  # UTC hour 22
        
        # File contents should be identical (except generated_at_utc timestamps)
        with open(file1, 'r') as f:
            data1 = json.load(f)
        with open(file2, 'r') as f:
            data2 = json.load(f)
        
        # Remove timestamps for comparison
        data1_copy = dict(data1)
        data2_copy = dict(data2)
        del data1_copy["generated_at_utc"]
        del data2_copy["generated_at_utc"]
        
        assert data1_copy == data2_copy

    def test_filename_utc_parsing(self, mock_config):
        """Test that filename parsing correctly handles UTC timestamps."""
        recorder = ResearchRecorder(
            mock_config,
            "dummy",
            summaries_dir="dummy"
        )
        
        # Test various valid UTC timestamps
        test_cases = [
            ("SYMBOL_2025-01-15_00.json", datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)),
            ("SYMBOL_2025-01-15_23.json", datetime(2025, 1, 15, 23, 0, 0, tzinfo=timezone.utc)),
            ("BTC_2024-12-31_12.json", datetime(2024, 12, 31, 12, 0, 0, tzinfo=timezone.utc)),
            ("TEST_2025-02-28_06.json", datetime(2025, 2, 28, 6, 0, 0, tzinfo=timezone.utc)),
        ]
        
        for filename, expected_utc in test_cases:
            parsed = recorder._parse_utc_from_filename(filename)
            assert parsed == expected_utc
            assert parsed.tzinfo == timezone.utc

    @pytest.mark.asyncio
    async def test_window_utc_boundaries_timezone_independent(self, tmp_path, mock_config):
        """Test that window_utc boundaries are always in UTC regardless of local timezone."""
        symbol = "WINDOW"
        
        original_tz = os.environ.get('TZ')
        
        try:
            # Set timezone to something far from UTC
            os.environ['TZ'] = 'Asia/Tokyo'  # UTC+9
            try:
                time.tzset()
            except AttributeError:
                pass
            
            recorder = ResearchRecorder(
                mock_config,
                str(tmp_path / "research"),
                summaries_dir=str(tmp_path / "summaries")
            )
            
            await recorder.start()
            
            try:
                # Use midnight UTC (which would be 9 AM in Tokyo)
                utc_midnight = datetime(2025, 1, 16, 0, 0, 0, tzinfo=timezone.utc)
                
                orderbook = self.create_test_orderbook(symbol)
                our_quotes = {"bids": [{"price": 149.99, "size": 1.0}], "asks": []}
                recorder.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
                
                with patch('src.storage.research_recorder.get_git_sha', return_value='window_sha'), \
                     patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='window_hash'):
                    await recorder._generate_hourly_summaries(utc_midnight)
                
                symbol_dir = tmp_path / "summaries" / symbol
                json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
                
                with open(json_files[0], 'r') as f:
                    data = json.load(f)
                
                # Window should be exactly UTC midnight to 1 AM
                assert data["window_utc"]["hour_start"] == "2025-01-16T00:00:00Z"
                assert data["window_utc"]["hour_end"] == "2025-01-16T01:00:00Z"
                
                # Filename should reflect UTC hour 00, not Tokyo hour 09
                assert json_files[0].name == f"{symbol}_2025-01-16_00.json"
                
            finally:
                await recorder.stop()
                
        finally:
            if original_tz is not None:
                os.environ['TZ'] = original_tz
            else:
                os.environ.pop('TZ', None)
            try:
                time.tzset()
            except AttributeError:
                pass

    @pytest.mark.asyncio
    async def test_recorder_current_hour_utc(self, tmp_path, mock_config):
        """Test that recorder's current_hour is always in UTC."""
        original_tz = os.environ.get('TZ')
        
        try:
            os.environ['TZ'] = 'America/New_York'  # UTC-5 or UTC-4
            try:
                time.tzset()
            except AttributeError:
                pass
            
            recorder = ResearchRecorder(
                mock_config,
                str(tmp_path / "research"),
                summaries_dir=str(tmp_path / "summaries")
            )
            
            # Check that current_hour is UTC-aware
            assert recorder.current_hour.tzinfo == timezone.utc
            
            # Check that it's properly normalized to hour boundary
            assert recorder.current_hour.minute == 0
            assert recorder.current_hour.second == 0
            assert recorder.current_hour.microsecond == 0
            
        finally:
            if original_tz is not None:
                os.environ['TZ'] = original_tz
            else:
                os.environ.pop('TZ', None)
            try:
                time.tzset()
            except AttributeError:
                pass

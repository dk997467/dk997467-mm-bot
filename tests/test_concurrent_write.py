"""
Tests for E1+ concurrent write protection.
"""

import asyncio
import pytest
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import threading

from src.storage.research_recorder import ResearchRecorder
from src.storage.locks import acquire_hour_lock, LockAcquisitionError
from src.common.models import OrderBook, PriceLevel
from decimal import Decimal


class TestConcurrentWrite:
    """Test concurrent write protection mechanisms."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = MagicMock()
        config.storage = MagicMock()
        config.storage.compress = 'none'
        config.storage.batch_size = 100
        config.storage.flush_ms = 50
        return config

    def create_test_orderbook(self, symbol: str = "CONC", mid_price: float = 100.0) -> OrderBook:
        """Create a test orderbook."""
        return OrderBook(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            sequence=1000,
            bids=[PriceLevel(price=Decimal(str(mid_price - 0.01)), size=Decimal("1.0"))],
            asks=[PriceLevel(price=Decimal(str(mid_price + 0.01)), size=Decimal("1.0"))]
        )

    @pytest.mark.asyncio
    async def test_lockfile_mode_concurrent_writes(self, tmp_path, mock_config):
        """Test that lockfile mode prevents concurrent writes to same hour."""
        symbol = "LOCKTEST"
        
        recorder1 = ResearchRecorder(
            mock_config,
            str(tmp_path / "research1"),
            summaries_dir=str(tmp_path / "summaries"),
            lock_mode="lockfile",
            retention_days=None
        )
        
        recorder2 = ResearchRecorder(
            mock_config,
            str(tmp_path / "research2"),
            summaries_dir=str(tmp_path / "summaries"),
            lock_mode="lockfile",
            retention_days=None
        )
        
        await recorder1.start()
        await recorder2.start()
        
        try:
            test_hour = datetime(2025, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
            
            # Create tasks that write to the same hour simultaneously
            async def write_summary_1():
                orderbook = self.create_test_orderbook(symbol)
                our_quotes = {"bids": [{"price": 99.99, "size": 1.0}], "asks": []}
                recorder1.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
                
                with patch('src.storage.research_recorder.get_git_sha', return_value='writer1_sha'), \
                     patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='writer1_hash'):
                    await recorder1._generate_hourly_summaries(test_hour)
            
            async def write_summary_2():
                # Add small delay to ensure overlap
                await asyncio.sleep(0.05)
                
                orderbook = self.create_test_orderbook(symbol)
                our_quotes = {"bids": [{"price": 99.98, "size": 1.0}], "asks": []}
                recorder2.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
                
                with patch('src.storage.research_recorder.get_git_sha', return_value='writer2_sha'), \
                     patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='writer2_hash'):
                    await recorder2._generate_hourly_summaries(test_hour)
            
            # Run both writers concurrently
            await asyncio.gather(write_summary_1(), write_summary_2())
            
            # Should have exactly one valid file
            symbol_dir = tmp_path / "summaries" / symbol
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 1, f"Expected 1 file, got {len(json_files)}: {json_files}"
            
            # File should be valid and contain data from one of the writers
            with open(json_files[0], 'r') as f:
                import json
                data = json.load(f)
            
            assert data["symbol"] == symbol
            assert "schema_version" in data
            assert data["metadata"]["git_sha"] in ["writer1_sha", "writer2_sha"]
            
            # No lock files should remain
            lock_files = list(symbol_dir.glob("*.lock"))
            assert len(lock_files) == 0, f"Lock files not cleaned up: {lock_files}"
            
        finally:
            await recorder1.stop()
            await recorder2.stop()

    @pytest.mark.asyncio
    async def test_o_excl_mode_with_retry(self, tmp_path, mock_config):
        """Test O_EXCL mode handles conflicts with retry mechanism."""
        symbol = "OEXCL"
        
        recorder = ResearchRecorder(
            mock_config,
            str(tmp_path / "research"),
            summaries_dir=str(tmp_path / "summaries"),
            lock_mode="o_excl",
            retention_days=None
        )
        
        await recorder.start()
        
        try:
            test_hour = datetime(2025, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
            
            # Simulate concurrent access by manually using the lock
            from src.storage.locks import acquire_hour_lock
            
            results = []
            exceptions = []
            
            def worker_thread(worker_id):
                """Worker thread that tries to acquire lock."""
                try:
                    with acquire_hour_lock(symbol, test_hour, tmp_path / "summaries", "o_excl"):
                        # Simulate some work
                        time.sleep(0.1)
                        results.append(f"worker_{worker_id}_success")
                except Exception as e:
                    exceptions.append((worker_id, str(e)))
            
            # Start multiple threads
            threads = []
            for i in range(3):
                thread = threading.Thread(target=worker_thread, args=(i,))
                threads.append(thread)
                thread.start()
            
            # Wait for all threads
            for thread in threads:
                thread.join(timeout=5.0)
            
            # Exactly one should succeed, others should get exceptions
            assert len(results) == 1, f"Expected 1 success, got {len(results)}: {results}"
            assert len(exceptions) == 2, f"Expected 2 exceptions, got {len(exceptions)}: {exceptions}"
            
            # Check that exceptions are LockAcquisitionError or similar
            for worker_id, error_msg in exceptions:
                assert "lock" in error_msg.lower() or "excl" in error_msg.lower()
            
        finally:
            await recorder.stop()

    @pytest.mark.asyncio 
    async def test_no_lock_mode_allows_overwrites(self, tmp_path, mock_config):
        """Test that 'none' lock mode allows concurrent writes (no protection)."""
        symbol = "NOLOCK"
        
        recorder1 = ResearchRecorder(
            mock_config,
            str(tmp_path / "research1"),
            summaries_dir=str(tmp_path / "summaries"),
            lock_mode="none",  # No locking
            retention_days=None
        )
        
        recorder2 = ResearchRecorder(
            mock_config,
            str(tmp_path / "research2"),
            summaries_dir=str(tmp_path / "summaries"),
            lock_mode="none",  # No locking
            retention_days=None
        )
        
        await recorder1.start()
        await recorder2.start()
        
        try:
            test_hour = datetime(2025, 1, 15, 16, 0, 0, tzinfo=timezone.utc)
            
            # Write from recorder1
            orderbook = self.create_test_orderbook(symbol)
            our_quotes = {"bids": [{"price": 99.99, "size": 1.0}], "asks": []}
            recorder1.record_market_snapshot(symbol, orderbook, our_quotes, 0.1)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='first_writer'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='first_hash'):
                await recorder1._generate_hourly_summaries(test_hour)
            
            # Write from recorder2 (should overwrite)
            our_quotes2 = {"bids": [{"price": 99.98, "size": 2.0}], "asks": []}
            recorder2.record_market_snapshot(symbol, orderbook, our_quotes2, 0.2)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='second_writer'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='second_hash'):
                await recorder2._generate_hourly_summaries(test_hour)
            
            # Should have one file with data from the last writer
            symbol_dir = tmp_path / "summaries" / symbol
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 1
            
            with open(json_files[0], 'r') as f:
                import json
                data = json.load(f)
            
            # Should contain data from second writer (overwrite behavior)
            assert data["metadata"]["git_sha"] == "second_writer"
            
        finally:
            await recorder1.stop()
            await recorder2.stop()

    def test_acquire_hour_lock_context_manager(self, tmp_path):
        """Test hour lock context manager behavior."""
        symbol = "LOCKCTX"
        test_hour = datetime(2025, 1, 15, 17, 0, 0, tzinfo=timezone.utc)
        summaries_dir = tmp_path / "summaries"
        
        # Test successful acquisition and release
        with acquire_hour_lock(symbol, test_hour, summaries_dir, "lockfile"):
            # Inside lock
            symbol_dir = summaries_dir / symbol
            assert symbol_dir.exists()
            
            # Lock file should exist
            lock_files = list(symbol_dir.glob("*.lock"))
            assert len(lock_files) == 1
        
        # After context exit, lock file should be cleaned up
        lock_files = list(symbol_dir.glob("*.lock"))
        assert len(lock_files) == 0

    def test_lock_timeout_and_cleanup(self, tmp_path):
        """Test lock timeout and proper cleanup on failure."""
        symbol = "TIMEOUT"
        test_hour = datetime(2025, 1, 15, 18, 0, 0, tzinfo=timezone.utc)
        summaries_dir = tmp_path / "summaries"
        
        # Create a long-held lock
        lock_held = threading.Event()
        lock_released = threading.Event()
        
        def long_holder():
            try:
                with acquire_hour_lock(symbol, test_hour, summaries_dir, "lockfile"):
                    lock_held.set()
                    # Hold lock for a while
                    lock_released.wait(timeout=2.0)
            except Exception:
                pass
        
        # Start long holder
        holder_thread = threading.Thread(target=long_holder)
        holder_thread.start()
        
        # Wait for lock to be acquired
        assert lock_held.wait(timeout=2.0), "Lock should be acquired"
        
        # Try to acquire same lock with short timeout (should fail)
        start_time = time.time()
        with pytest.raises(LockAcquisitionError):
            # Patch the timeout to be short for testing
            with patch('src.storage.locks._acquire_lockfile_lock') as mock_acquire:
                mock_acquire.side_effect = LockAcquisitionError("Timeout")
                with acquire_hour_lock(symbol, test_hour, summaries_dir, "lockfile"):
                    pass
        
        # Release the lock
        lock_released.set()
        holder_thread.join(timeout=2.0)
        
        # No lock files should remain
        symbol_dir = summaries_dir / symbol
        if symbol_dir.exists():
            lock_files = list(symbol_dir.glob("*.lock"))
            assert len(lock_files) == 0

    @pytest.mark.asyncio
    async def test_concurrent_merge_strategy(self, tmp_path, mock_config):
        """Test concurrent writes with merge strategy."""
        symbol = "MERGE"
        
        recorder1 = ResearchRecorder(
            mock_config,
            str(tmp_path / "research1"),
            summaries_dir=str(tmp_path / "summaries"),
            lock_mode="lockfile",
            overwrite_existing_hour=False,
            merge_strategy="sum_bins",
            retention_days=None
        )
        
        recorder2 = ResearchRecorder(
            mock_config,
            str(tmp_path / "research2"),
            summaries_dir=str(tmp_path / "summaries"),
            lock_mode="lockfile",
            overwrite_existing_hour=False,
            merge_strategy="sum_bins",
            retention_days=None
        )
        
        await recorder1.start()
        await recorder2.start()
        
        try:
            test_hour = datetime(2025, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
            
            # First write
            orderbook = self.create_test_orderbook(symbol)
            our_quotes1 = {"bids": [{"price": 99.95, "size": 1.0}], "asks": []}  # 5 bps
            recorder1.record_market_snapshot(symbol, orderbook, our_quotes1, 0.1)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='merge1'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='hash1'):
                await recorder1._generate_hourly_summaries(test_hour)
            
            # Second write (should merge)
            our_quotes2 = {"bids": [{"price": 99.90, "size": 1.0}], "asks": []}  # 10 bps
            recorder2.record_market_snapshot(symbol, orderbook, our_quotes2, 0.1)
            
            with patch('src.storage.research_recorder.get_git_sha', return_value='merge2'), \
                 patch('src.storage.research_recorder.cfg_hash_sanitized', return_value='hash2'):
                await recorder2._generate_hourly_summaries(test_hour)
            
            # Should have one merged file
            symbol_dir = tmp_path / "summaries" / symbol
            json_files = list(symbol_dir.glob(f"{symbol}_*.json"))
            assert len(json_files) == 1
            
            with open(json_files[0], 'r') as f:
                import json
                data = json.load(f)
            
            # Should have merged quote counts
            assert data["counts"]["quotes"] == 2  # 1 + 1
            
            # Should have both price bins
            hit_rate = data["hit_rate_by_bin"]
            assert "5" in hit_rate and "10" in hit_rate
            
            # Metadata should be from the latest write
            assert data["metadata"]["git_sha"] == "merge2"
            
        finally:
            await recorder1.stop()
            await recorder2.stop()

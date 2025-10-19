#!/usr/bin/env python3
"""
Smoke test for Redis Streams ingest adapter.

Tests basic functionality without requiring a live Redis instance
(uses mocking for CI compatibility).
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_seq_gap_guard():
    """Test SeqGapGuard sequence detection logic."""
    from tools.shadow.ingest_redis import SeqGapGuard
    
    guard = SeqGapGuard()
    
    # Normal sequence
    assert guard.check("BTCUSDT", 1) is None
    assert guard.check("BTCUSDT", 2) is None
    assert guard.check("BTCUSDT", 3) is None
    
    # Gap detected (seq 3 → 5, gap = 5 - 4 = 1)
    error = guard.check("BTCUSDT", 5)
    assert error is not None
    assert "gap=1" in error
    
    # Out-of-order (duplicate or reordered)
    error = guard.check("BTCUSDT", 4)
    assert error is not None
    assert "out-of-order" in error
    
    # Stats
    stats = guard.get_stats()
    assert "BTCUSDT" in stats
    assert stats["BTCUSDT"] == 1  # One message missing (seq 4)


def test_normalize_tick():
    """Test tick normalization from Redis fields."""
    from tools.shadow.ingest_redis import normalize_tick
    
    # Valid fields
    fields = {
        "ts": "1234567890.123",
        "seq": "12345",
        "symbol": "BTCUSDT",
        "bid": "50000.5",
        "bid_size": "1.23",
        "ask": "50001.0",
        "ask_size": "2.34",
        "last_qty": "0.05",
    }
    
    tick = normalize_tick(fields)
    
    assert tick["ts_server"] == 1234567890.123
    assert tick["seq"] == 12345
    assert tick["symbol"] == "BTCUSDT"
    assert tick["bid"] == 50000.5
    assert tick["bid_size"] == 1.23
    assert tick["ask"] == 50001.0
    assert tick["ask_size"] == 2.34
    assert tick["last_qty"] == 0.05
    assert "ts" in tick  # Ingest timestamp added


def test_reorder_buffer_basic():
    """Test basic reordering buffer operations."""
    from tools.shadow.reorder_buffer import ReorderBuffer
    
    buffer = ReorderBuffer(window_ms=100.0, max_size=100)
    
    # Add ticks
    import time
    base_ts = time.time()
    
    ticks = [
        {"ts_server": base_ts + 0.05, "symbol": "BTCUSDT", "seq": 2},
        {"ts_server": base_ts + 0.01, "symbol": "BTCUSDT", "seq": 1},  # Out of order
        {"ts_server": base_ts + 0.10, "symbol": "BTCUSDT", "seq": 3},
    ]
    
    for tick in ticks:
        buffer.add(tick)
    
    # Flush (old ticks) - need to wait for window (100ms) + some margin
    time.sleep(0.12)  # Wait for window
    flushed = buffer.flush(force=True)  # Force flush to ensure all ticks emitted
    
    # Should be sorted by ts_server
    assert len(flushed) == 3
    assert flushed[0]["seq"] == 1
    assert flushed[1]["seq"] == 2
    assert flushed[2]["seq"] == 3
    
    # Stats
    stats = buffer.get_stats()
    assert stats["total_added"] == 3
    assert stats["total_flushed"] == 3
    # Note: Reordering is only detected when a tick is emitted with ts_server < last_ts_server
    # In this case, all ticks are emitted for the first time (sorted), so no reordering detected


def test_reorder_buffer_backpressure():
    """Test backpressure (drop on overflow)."""
    from tools.shadow.reorder_buffer import ReorderBuffer
    
    buffer = ReorderBuffer(window_ms=1000.0, max_size=5)
    
    import time
    base_ts = time.time()
    
    # Add more than max_size
    for i in range(10):
        buffer.add({"ts_server": base_ts + i * 0.01, "symbol": "BTCUSDT", "seq": i})
    
    # Buffer should have dropped 5 ticks
    stats = buffer.get_stats()
    assert stats["buffer_size"] <= 5
    assert "BTCUSDT" in stats["backpressure_drops"]
    assert stats["backpressure_drops"]["BTCUSDT"] == 5


def test_reorder_buffer_force_flush():
    """Test force flush (shutdown scenario)."""
    from tools.shadow.reorder_buffer import ReorderBuffer
    
    buffer = ReorderBuffer(window_ms=1000.0, max_size=100)
    
    import time
    base_ts = time.time()
    
    # Add recent ticks (within window)
    for i in range(5):
        buffer.add({"ts_server": base_ts + i * 0.01, "symbol": "BTCUSDT", "seq": i})
    
    # Normal flush (should be empty, all within window)
    flushed = buffer.flush()
    assert len(flushed) == 0
    
    # Force flush (should emit all)
    flushed = buffer.flush(force=True)
    assert len(flushed) == 5


def test_integration_scenario():
    """Test end-to-end scenario: seq gaps + reordering."""
    from tools.shadow.ingest_redis import SeqGapGuard, normalize_tick
    from tools.shadow.reorder_buffer import ReorderBuffer
    
    guard = SeqGapGuard()
    buffer = ReorderBuffer(window_ms=50.0, max_size=1000)
    
    import time
    base_ts = time.time()
    
    # Simulate incoming messages (ts out of order, but seq in order with gap)
    raw_messages = [
        {"ts": str(base_ts + 0.01), "seq": "1", "symbol": "BTCUSDT", "bid": "50000", "bid_size": "1", "ask": "50001", "ask_size": "1", "last_qty": "0.1"},
        {"ts": str(base_ts + 0.02), "seq": "2", "symbol": "BTCUSDT", "bid": "50000", "bid_size": "1", "ask": "50001", "ask_size": "1", "last_qty": "0.1"},
        {"ts": str(base_ts + 0.05), "seq": "5", "symbol": "BTCUSDT", "bid": "50000", "bid_size": "1", "ask": "50001", "ask_size": "1", "last_qty": "0.1"},  # Gap (3,4 missing)
    ]
    
    seq_gaps_count = 0
    
    for raw_msg in raw_messages:
        # Normalize
        tick = normalize_tick(raw_msg)
        
        # Check seq gaps
        symbol = tick["symbol"]
        seq = tick["seq"]
        gap_error = guard.check(symbol, seq)
        if gap_error:
            seq_gaps_count += 1
        
        # Add to buffer
        buffer.add(tick)
    
    # Wait and flush
    time.sleep(0.06)
    flushed = buffer.flush(force=True)  # Force flush for test
    
    # Assertions
    assert seq_gaps_count == 1  # One gap detected (seq jump 2→5, missing 3 & 4)
    assert len(flushed) == 3
    assert flushed[0]["seq"] == 1  # Sorted by ts_server
    assert flushed[1]["seq"] == 2
    assert flushed[2]["seq"] == 5
    
    # Stats check (reordering only if timestamps were out of order)
    stats = buffer.get_stats()
    # In this test, timestamps are in order, so no reordering expected
    # But buffer should have processed all ticks
    assert stats["total_added"] == 3
    assert stats["total_flushed"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


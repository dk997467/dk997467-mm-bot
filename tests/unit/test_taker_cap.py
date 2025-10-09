"""
Unit tests for taker cap enforcement.

Tests that taker fills are tracked correctly and limits are enforced
to prevent excessive slippage.
"""
import pytest
import time
from src.execution.taker_tracker import TakerTracker


@pytest.fixture
def tracker():
    """Create TakerTracker with test config."""
    return TakerTracker(
        max_taker_fills_per_hour=10,
        max_taker_share_pct=25.0,  # 25% max
        rolling_window_sec=60  # 1 minute window for faster testing
    )


def test_empty_tracker_allows_taker(tracker):
    """Test that empty tracker allows taker fills."""
    can_take, reason = tracker.can_take_liquidity()
    assert can_take is True
    assert reason == ""


def test_record_and_retrieve_fills(tracker):
    """Test basic fill recording and stats retrieval."""
    now_ms = int(time.time() * 1000)
    
    # Record 5 maker fills and 2 taker fills
    for i in range(5):
        tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms + i)
    
    for i in range(2):
        tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=now_ms + 100 + i)
    
    stats = tracker.get_stats()
    
    assert stats['taker_count'] == 2
    assert stats['maker_count'] == 5
    assert stats['total_count'] == 7
    assert stats['taker_share_pct'] == pytest.approx(28.57, rel=0.1)  # 2/7 ≈ 28.57%
    assert stats['can_take'] is False  # Exceeds 25% share limit


def test_count_limit_enforcement(tracker):
    """Test that absolute count limit is enforced."""
    now_ms = int(time.time() * 1000)
    
    # Record 10 taker fills (at the limit)
    for i in range(10):
        tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=now_ms + i)
    
    stats = tracker.get_stats()
    assert stats['taker_count'] == 10
    assert stats['can_take'] is False  # At limit, new taker would exceed
    
    # Try to add one more
    can_take, reason = tracker.can_take_liquidity()
    assert can_take is False
    assert "taker_count_exceeded" in reason


def test_share_limit_enforcement(tracker):
    """Test that percentage share limit is enforced."""
    now_ms = int(time.time() * 1000)
    
    # Record fills: 3 taker, 7 maker = 30% taker share
    for i in range(7):
        tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms + i)
    
    for i in range(3):
        tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=now_ms + 100 + i)
    
    stats = tracker.get_stats()
    assert stats['taker_share_pct'] == pytest.approx(30.0, rel=0.1)
    
    # Adding one more taker: 4/11 = 36.4% (still exceeds 25% limit)
    can_take, reason = tracker.can_take_liquidity()
    assert can_take is False
    assert "taker_share_exceeded" in reason


def test_rolling_window_cleanup(tracker):
    """Test that old fills are removed from rolling window."""
    now_ms = int(time.time() * 1000)
    
    # Record fills 2 minutes ago (outside 1-minute window)
    old_timestamp = now_ms - (120 * 1000)  # 2 minutes ago
    for i in range(5):
        tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=old_timestamp + i)
    
    # Check stats with current timestamp (should trigger cleanup)
    stats = tracker.get_stats(timestamp_ms=now_ms)
    
    assert stats['taker_count'] == 0
    assert stats['total_count'] == 0
    assert len(tracker.fills) == 0  # All fills should be cleaned up


def test_gradual_fill_decay(tracker):
    """Test that fills gradually decay from rolling window."""
    now_ms = int(time.time() * 1000)
    window_ms = tracker.rolling_window_ms
    
    # Record fills at various times within window
    timestamps = [
        now_ms - window_ms + 1000,  # Just inside window
        now_ms - (window_ms // 2),  # Middle of window
        now_ms - 1000,              # Recent
    ]
    
    for ts in timestamps:
        tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=ts)
    
    # All 3 should be in window
    stats1 = tracker.get_stats(timestamp_ms=now_ms)
    assert stats1['taker_count'] == 3
    
    # Advance time by 2 seconds (oldest should fall out)
    future_ms = now_ms + 2000
    stats2 = tracker.get_stats(timestamp_ms=future_ms)
    assert stats2['taker_count'] == 2


def test_allows_taker_when_under_limits(tracker):
    """Test that taker fills are allowed when under both limits."""
    now_ms = int(time.time() * 1000)
    
    # Record fills well under limits: 2 taker, 10 maker = 16.7% taker share
    for i in range(10):
        tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms + i)
    
    for i in range(2):
        tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=now_ms + 100 + i)
    
    stats = tracker.get_stats()
    assert stats['taker_share_pct'] < 25.0
    assert stats['taker_count'] < 10
    
    # Should allow taker fill
    can_take, reason = tracker.can_take_liquidity()
    assert can_take is True
    assert reason == ""


def test_minimum_sample_size(tracker):
    """Test that percentage limit requires minimum sample size."""
    now_ms = int(time.time() * 1000)
    
    # Record only 5 fills (below minimum of 10)
    tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=now_ms)
    tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms + 1)
    tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms + 2)
    tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms + 3)
    tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms + 4)
    
    stats = tracker.get_stats()
    assert stats['total_count'] == 5
    assert stats['taker_share_pct'] == 20.0  # 1/5 = 20%
    
    # Should allow taker fill (sample size too small for percentage check)
    can_take, reason = tracker.can_take_liquidity()
    assert can_take is True  # Not blocked by share limit due to small sample


def test_reset_clears_all_fills(tracker):
    """Test that reset() clears all tracked fills."""
    now_ms = int(time.time() * 1000)
    
    # Record some fills
    for i in range(10):
        tracker.record_fill("BTCUSDT", is_taker=(i % 2 == 0), timestamp_ms=now_ms + i)
    
    assert len(tracker.fills) == 10
    
    # Reset
    tracker.reset()
    
    assert len(tracker.fills) == 0
    stats = tracker.get_stats()
    assert stats['total_count'] == 0
    assert stats['taker_count'] == 0
    assert stats['can_take'] is True


def test_multiple_symbols(tracker):
    """Test that tracker works with multiple symbols (basic test)."""
    now_ms = int(time.time() * 1000)
    
    # Record fills for different symbols
    tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=now_ms)
    tracker.record_fill("ETHUSDT", is_taker=True, timestamp_ms=now_ms + 1)
    tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms + 2)
    
    # Currently tracker is global (not per-symbol)
    stats = tracker.get_stats()
    assert stats['total_count'] == 3
    assert stats['taker_count'] == 2


def test_concurrent_taker_and_maker_fills(tracker):
    """Test mixed taker/maker fills at same timestamps."""
    now_ms = int(time.time() * 1000)
    
    # Record simultaneous fills
    tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=now_ms)
    tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms)
    tracker.record_fill("BTCUSDT", is_taker=True, timestamp_ms=now_ms)
    tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms)
    
    stats = tracker.get_stats()
    assert stats['total_count'] == 4
    assert stats['taker_count'] == 2
    assert stats['maker_count'] == 2
    assert stats['taker_share_pct'] == 50.0


def test_edge_case_zero_price_move(tracker):
    """Test that tracker handles edge cases gracefully."""
    now_ms = int(time.time() * 1000)
    
    # Record many maker fills, no taker fills
    for i in range(20):
        tracker.record_fill("BTCUSDT", is_taker=False, timestamp_ms=now_ms + i)
    
    stats = tracker.get_stats()
    assert stats['taker_share_pct'] == 0.0
    
    # Should allow taker fill (0% < 25% limit)
    can_take, reason = tracker.can_take_liquidity()
    assert can_take is True


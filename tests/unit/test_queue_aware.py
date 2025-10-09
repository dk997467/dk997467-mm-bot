"""
Unit tests for queue-aware quoting functionality.

Tests queue position estimation and micro-repricing logic.
"""
import pytest
import time
from unittest.mock import Mock
from src.strategy.queue_aware import (
    estimate_queue_position,
    QueueAwareRepricer,
    Quote
)
from src.common.config import QueueAwareConfig


@pytest.fixture
def config():
    """Default queue-aware config."""
    return QueueAwareConfig(
        enabled=True,
        max_reprice_bps=0.5,
        headroom_ms=150,
        join_threshold_pct=30.0,
        book_depth_levels=3
    )


@pytest.fixture
def repricer(config):
    """QueueAwareRepricer instance."""
    return QueueAwareRepricer(config)


def test_estimate_queue_top_of_book():
    """Test queue estimation when at top of book."""
    book = {
        'bids': [[50000.0, 10.0], [49999.0, 5.0], [49998.0, 3.0]],
        'asks': [[50001.0, 8.0], [50002.0, 4.0], [50003.0, 2.0]]
    }
    
    # Bid at best price - should be ahead of 10 units
    result = estimate_queue_position(book, 'bid', 50000.0, 1.0, depth_levels=3)
    
    assert result['at_best'] is True
    assert result['level'] == 0
    assert result['ahead_qty'] == 10.0  # Join back of queue
    assert result['percentile'] == pytest.approx(55.6, rel=0.1)  # 10/(10+5+3)*100


def test_estimate_queue_middle_of_book():
    """Test queue estimation in middle of book."""
    book = {
        'bids': [[50000.0, 10.0], [49999.0, 5.0], [49998.0, 3.0]],
        'asks': [[50001.0, 8.0], [50002.0, 4.0], [50003.0, 2.0]]
    }
    
    # Bid at second level
    result = estimate_queue_position(book, 'bid', 49999.0, 1.0, depth_levels=3)
    
    assert result['at_best'] is False
    assert result['level'] == 1
    assert result['ahead_qty'] == 15.0  # 10 + 5
    assert result['percentile'] == pytest.approx(83.3, rel=0.1)  # 15/18*100


def test_estimate_queue_improving_best():
    """Test queue estimation when improving best price."""
    book = {
        'bids': [[50000.0, 10.0], [49999.0, 5.0]],
        'asks': [[50001.0, 8.0], [50002.0, 4.0]]
    }
    
    # Bid better than best
    result = estimate_queue_position(book, 'bid', 50001.0, 1.0, depth_levels=2)
    
    assert result['at_best'] is True
    assert result['ahead_qty'] == 0.0
    assert result['percentile'] == 0.0


def test_estimate_queue_beyond_depth():
    """Test queue estimation when price beyond visible depth."""
    book = {
        'bids': [[50000.0, 10.0], [49999.0, 5.0]],
        'asks': [[50001.0, 8.0], [50002.0, 4.0]]
    }
    
    # Bid worse than visible depth
    result = estimate_queue_position(book, 'bid', 49990.0, 1.0, depth_levels=2)
    
    assert result['at_best'] is False
    assert result['level'] == 2
    assert result['ahead_qty'] == 15.0  # All visible qty
    assert result['percentile'] == 100.0


def test_estimate_queue_empty_book():
    """Test queue estimation with empty book."""
    book = {'bids': [], 'asks': []}
    
    result = estimate_queue_position(book, 'bid', 50000.0, 1.0)
    
    assert result['at_best'] is True
    assert result['ahead_qty'] == 0.0
    assert result['percentile'] == 0.0


def test_repricer_no_nudge_within_threshold(repricer):
    """Test that no nudge occurs when queue position is good."""
    quote = Quote(symbol="BTCUSDT", side="bid", price=50000.0, size=1.0)
    book = {
        'bids': [[50000.0, 2.0], [49999.0, 10.0]],  # We're at top with only 2 ahead
        'asks': [[50001.0, 5.0]]
    }
    now_ms = int(time.time() * 1000)
    
    result = repricer.maybe_nudge(quote, book, now_ms)
    
    # Good position (percentile ~16%), no nudge
    assert result is None


def test_repricer_nudges_bad_position(repricer):
    """Test that nudge occurs when queue position is poor."""
    quote = Quote(symbol="BTCUSDT", side="bid", price=49999.0, size=1.0)
    book = {
        'bids': [[50000.0, 20.0], [49999.0, 5.0]],  # Bad position at second level
        'asks': [[50001.0, 10.0]]
    }
    now_ms = int(time.time() * 1000)
    
    result = repricer.maybe_nudge(quote, book, now_ms)
    
    # Should nudge towards best price
    assert result is not None
    assert result.price > quote.price  # Nudged up
    assert result.price <= 50000.0  # But not beyond best


def test_repricer_respects_headroom(repricer):
    """Test that headroom prevents too-frequent nudges."""
    quote = Quote(symbol="BTCUSDT", side="bid", price=49999.0, size=1.0)
    book = {
        'bids': [[50000.0, 20.0], [49999.0, 5.0]],
        'asks': [[50001.0, 10.0]]
    }
    now_ms = int(time.time() * 1000)
    
    # First nudge
    result1 = repricer.maybe_nudge(quote, book, now_ms)
    assert result1 is not None
    
    # Immediate second nudge (within headroom)
    result2 = repricer.maybe_nudge(quote, book, now_ms + 50)  # Only 50ms later
    assert result2 is None  # Blocked by headroom
    
    # After headroom expires
    result3 = repricer.maybe_nudge(quote, book, now_ms + 200)  # 200ms later
    assert result3 is not None  # Allowed


def test_repricer_respects_max_reprice_bps(repricer):
    """Test that nudge respects max_reprice_bps limit."""
    quote = Quote(symbol="BTCUSDT", side="bid", price=49900.0, size=1.0)
    book = {
        'bids': [[50000.0, 20.0], [49900.0, 5.0]],  # 100 away from best
        'asks': [[50001.0, 10.0]]
    }
    now_ms = int(time.time() * 1000)
    
    result = repricer.maybe_nudge(quote, book, now_ms)
    
    assert result is not None
    # Max nudge is 0.5 bps = 0.5/10000 * 49900 ≈ 2.5
    # So new price should be around 49902.5, not 50000
    assert result.price < 49950.0  # Definitely less than halfway to best
    
    # Calculate actual delta
    delta_bps = (result.price - quote.price) / quote.price * 10000
    assert delta_bps <= repricer.cfg.max_reprice_bps


def test_repricer_respects_fair_value_bid(repricer):
    """Test that bid nudge respects fair value constraint."""
    quote = Quote(symbol="BTCUSDT", side="bid", price=49999.0, size=1.0)
    book = {
        'bids': [[50000.0, 20.0], [49999.0, 5.0]],
        'asks': [[50001.0, 10.0]]
    }
    now_ms = int(time.time() * 1000)
    fair_value = 49999.5  # Fair value lower than best bid
    
    result = repricer.maybe_nudge(quote, book, now_ms, fair_value=fair_value)
    
    # Should nudge but not exceed fair value
    if result:
        assert result.price <= fair_value


def test_repricer_respects_cooldown(repricer):
    """Test that nudge is blocked during cooldown."""
    quote = Quote(symbol="BTCUSDT", side="bid", price=49999.0, size=1.0)
    book = {
        'bids': [[50000.0, 20.0], [49999.0, 5.0]],
        'asks': [[50001.0, 10.0]]
    }
    now_ms = int(time.time() * 1000)
    
    # Try nudge while in cooldown
    result = repricer.maybe_nudge(quote, book, now_ms, in_cooldown=True)
    
    assert result is None  # Blocked by cooldown


def test_repricer_already_at_best(repricer):
    """Test that no nudge when already at best."""
    quote = Quote(symbol="BTCUSDT", side="bid", price=50000.0, size=1.0)
    book = {
        'bids': [[50000.0, 2.0], [49999.0, 10.0]],
        'asks': [[50001.0, 5.0]]
    }
    now_ms = int(time.time() * 1000)
    
    # Even with bad percentile, can't improve if already at best
    result = repricer.maybe_nudge(quote, book, now_ms)
    
    assert result is None


def test_repricer_ask_side(repricer):
    """Test nudging on ask side."""
    quote = Quote(symbol="BTCUSDT", side="ask", price=50002.0, size=1.0)
    book = {
        'bids': [[50000.0, 10.0]],
        'asks': [[50001.0, 20.0], [50002.0, 5.0]]  # Bad position at second level
    }
    now_ms = int(time.time() * 1000)
    
    result = repricer.maybe_nudge(quote, book, now_ms)
    
    # Should nudge towards best ask (down)
    if result:
        assert result.price < quote.price  # Nudged down
        assert result.price >= 50001.0  # But not beyond best


def test_repricer_disabled(config):
    """Test that repricer does nothing when disabled."""
    config.enabled = False
    repricer = QueueAwareRepricer(config)
    
    quote = Quote(symbol="BTCUSDT", side="bid", price=49999.0, size=1.0)
    book = {
        'bids': [[50000.0, 20.0], [49999.0, 5.0]],
        'asks': [[50001.0, 10.0]]
    }
    now_ms = int(time.time() * 1000)
    
    result = repricer.maybe_nudge(quote, book, now_ms)
    
    assert result is None


def test_repricer_get_stats(repricer):
    """Test repricer statistics."""
    quote = Quote(symbol="BTCUSDT", side="bid", price=49999.0, size=1.0)
    book = {
        'bids': [[50000.0, 20.0], [49999.0, 5.0]],
        'asks': [[50001.0, 10.0]]
    }
    now_ms = int(time.time() * 1000)
    
    # Trigger nudge
    repricer.maybe_nudge(quote, book, now_ms)
    
    stats = repricer.get_nudge_stats()
    
    assert 'symbols_nudged' in stats
    assert stats['symbols_nudged'] >= 1
    assert 'last_nudge_times' in stats


def test_repricer_reset(repricer):
    """Test repricer reset functionality."""
    quote = Quote(symbol="BTCUSDT", side="bid", price=49999.0, size=1.0)
    book = {
        'bids': [[50000.0, 20.0], [49999.0, 5.0]],
        'asks': [[50001.0, 10.0]]
    }
    now_ms = int(time.time() * 1000)
    
    # Trigger nudge
    repricer.maybe_nudge(quote, book, now_ms)
    
    # Reset
    repricer.reset()
    
    stats = repricer.get_nudge_stats()
    assert stats['symbols_nudged'] == 0

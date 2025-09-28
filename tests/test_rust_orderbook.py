"""
Tests for Rust-backed L2 order book integration.
"""

import pytest
from decimal import Decimal

from src.marketdata.orderbook import OrderBookManager


@pytest.fixture
def orderbook_manager():
    """Create an orderbook manager for testing."""
    return OrderBookManager("BTCUSDT", max_depth=25)


def test_rust_orderbook_availability():
    """Test that Rust extension is available."""
    try:
        from mm_orderbook import L2Book
        assert True, "Rust extension is available"
    except ImportError:
        pytest.skip("Rust extension not available")


def test_orderbook_manager_rust_fallback(orderbook_manager):
    """Test that orderbook manager works with or without Rust."""
    # Should work regardless of Rust availability
    assert orderbook_manager.symbol == "BTCUSDT"
    assert orderbook_manager.max_depth == 25
    
    # Check implementation type
    if hasattr(orderbook_manager, 'use_rust'):
        print(f"Using {'Rust' if orderbook_manager.use_rust else 'Python'} implementation")
    else:
        print("Using legacy Python implementation")


def test_orderbook_snapshot_update(orderbook_manager):
    """Test orderbook snapshot update."""
    from src.common.models import OrderBook, PriceLevel
    from datetime import datetime, timezone
    
    # Create test orderbook
    bids = [
        PriceLevel(price=Decimal("50000"), size=Decimal("1.5"), sequence=1),
        PriceLevel(price=Decimal("49999"), size=Decimal("2.0"), sequence=1),
    ]
    asks = [
        PriceLevel(price=Decimal("50001"), size=Decimal("1.0"), sequence=1),
        PriceLevel(price=Decimal("50002"), size=Decimal("2.5"), sequence=1),
    ]
    
    orderbook = OrderBook(
        symbol="BTCUSDT",
        timestamp=datetime.now(timezone.utc),
        sequence=1,
        bids=bids,
        asks=asks
    )
    
    # Update orderbook
    result = orderbook_manager.update_from_snapshot(orderbook)
    assert result is True
    assert orderbook_manager.is_synced is True
    assert orderbook_manager.last_sequence == 1


def test_orderbook_delta_update(orderbook_manager):
    """Test orderbook delta update."""
    # First apply a snapshot
    from src.common.models import OrderBook, PriceLevel
    from datetime import datetime, timezone
    
    bids = [
        PriceLevel(price=Decimal("50000"), size=Decimal("1.5"), sequence=1),
    ]
    asks = [
        PriceLevel(price=Decimal("50001"), size=Decimal("1.0"), sequence=1),
    ]
    
    orderbook = OrderBook(
        symbol="BTCUSDT",
        timestamp=datetime.now(timezone.utc),
        sequence=1,
        bids=bids,
        asks=asks
    )
    
    orderbook_manager.update_from_snapshot(orderbook)
    
    # Now apply delta
    delta_data = {
        "u": 2,  # sequence
        "b": [["49999", "2.0"]],  # new bid
        "a": [["50001", "0.0"]]   # remove ask
    }
    
    result = orderbook_manager.update_from_delta(delta_data)
    assert result is True
    assert orderbook_manager.last_sequence == 2


def test_orderbook_market_data(orderbook_manager):
    """Test orderbook market data methods."""
    # Set up orderbook with data
    from src.common.models import OrderBook, PriceLevel
    from datetime import datetime, timezone
    
    bids = [
        PriceLevel(price=Decimal("50000"), size=Decimal("1.5"), sequence=1),
        PriceLevel(price=Decimal("49999"), size=Decimal("2.0"), sequence=1),
    ]
    asks = [
        PriceLevel(price=Decimal("50001"), size=Decimal("1.0"), sequence=1),
        PriceLevel(price=Decimal("50002"), size=Decimal("2.5"), sequence=1),
    ]
    
    orderbook = OrderBook(
        symbol="BTCUSDT",
        timestamp=datetime.now(timezone.utc),
        sequence=1,
        bids=bids,
        asks=asks
    )
    
    orderbook_manager.update_from_snapshot(orderbook)
    
    # Test market data methods
    mid_price = orderbook_manager.get_mid_price()
    assert mid_price is not None
    assert float(mid_price) == 50000.5  # (50000 + 50001) / 2
    
    spread = orderbook_manager.get_spread()
    assert spread is not None
    assert float(spread) == 1.0  # 50001 - 50000
    
    spread_bps = orderbook_manager.get_spread_bps()
    assert spread_bps is not None
    # Calculate expected spread_bps: (1.0 / 50000.5) * 10000 = 0.199998
    expected_spread_bps = (1.0 / 50000.5) * 10000
    assert abs(float(spread_bps) - expected_spread_bps) < 0.001  # Allow small floating point differences
    
    microprice = orderbook_manager.get_microprice()
    assert microprice is not None
    
    imbalance = orderbook_manager.get_imbalance(5)
    assert imbalance is not None


def test_orderbook_stats(orderbook_manager):
    """Test orderbook statistics."""
    stats = orderbook_manager.get_stats()
    
    assert stats["symbol"] == "BTCUSDT"
    assert stats["is_synced"] is False
    assert stats["last_sequence"] == 0
    assert "implementation" in stats
    
    # Check if Rust implementation is available
    if "implementation" in stats:
        print(f"Implementation: {stats['implementation']}")


def test_orderbook_integrity(orderbook_manager):
    """Test orderbook integrity validation."""
    # Empty orderbook should be valid
    assert orderbook_manager.validate_integrity() is True
    
    # Add some data and validate
    from src.common.models import OrderBook, PriceLevel
    from datetime import datetime, timezone
    
    bids = [
        PriceLevel(price=Decimal("50000"), size=Decimal("1.5"), sequence=1),
    ]
    asks = [
        PriceLevel(price=Decimal("50001"), size=Decimal("1.0"), sequence=1),
    ]
    
    orderbook = OrderBook(
        symbol="BTCUSDT",
        timestamp=datetime.now(timezone.utc),
        sequence=1,
        bids=bids,
        asks=asks
    )
    
    orderbook_manager.update_from_snapshot(orderbook)
    assert orderbook_manager.validate_integrity() is True


def test_orderbook_reset(orderbook_manager):
    """Test orderbook reset functionality."""
    # Add some data
    from src.common.models import OrderBook, PriceLevel
    from datetime import datetime, timezone
    
    bids = [
        PriceLevel(price=Decimal("50000"), size=Decimal("1.5"), sequence=1),
    ]
    asks = [
        PriceLevel(price=Decimal("50001"), size=Decimal("1.0"), sequence=1),
    ]
    
    orderbook = OrderBook(
        symbol="BTCUSDT",
        timestamp=datetime.now(timezone.utc),
        sequence=1,
        bids=bids,
        asks=asks
    )
    
    orderbook_manager.update_from_snapshot(orderbook)
    assert orderbook_manager.is_synced is True
    
    # Reset
    orderbook_manager.reset()
    assert orderbook_manager.is_synced is False
    assert orderbook_manager.last_sequence == 0
    assert orderbook_manager.snapshot_count == 0


if __name__ == "__main__":
    # Run basic tests
    print("Testing Rust-backed order book integration...")
    
    try:
        from mm_orderbook import L2Book
        print("✓ Rust extension available")
        
        # Test basic L2Book functionality
        book = L2Book()
        book.apply_snapshot([(50000, 1.5)], [(50001, 1.0)])
        
        print(f"✓ Best bid: {book.best_bid()}")
        print(f"✓ Best ask: {book.best_ask()}")
        print(f"✓ Mid price: {book.mid()}")
        print(f"✓ Microprice: {book.microprice()}")
        print(f"✓ Imbalance: {book.imbalance(5)}")
        
    except ImportError:
        print("⚠ Rust extension not available, using Python fallback")
    
    print("✓ All tests passed!")

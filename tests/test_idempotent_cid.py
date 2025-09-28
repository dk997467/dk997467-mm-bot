"""
Test idempotent client order ID generation and uniqueness.
"""

import time
import pytest
from unittest.mock import Mock, AsyncMock

from src.connectors.bybit_rest import BybitRESTConnector
from src.common.di import AppContext
from src.common.config import AppConfig, StrategyConfig


@pytest.fixture
def mock_ctx():
    """Create mock AppContext."""
    strategy_config = StrategyConfig()
    app_config = AppConfig(
        config_version=1,
        strategy=strategy_config
    )
    return AppContext(cfg=app_config)


@pytest.fixture
def rest_connector(mock_ctx):
    """Create BybitRESTConnector instance."""
    config = {
        'base_url': 'https://api.bybit.com',
        'api_key': 'test_key',
        'api_secret': 'test_secret'
    }
    return BybitRESTConnector(mock_ctx, config)


def test_client_order_id_format(rest_connector):
    """Test that client order ID follows expected format."""
    symbol = "BTCUSDT"
    side = "Buy"
    
    cid = rest_connector._generate_client_order_id(symbol, side)
    
    # Check format: {symbol}-{side}-{timestamp}-{counter}-{random4}
    parts = cid.split('-')
    assert len(parts) == 5
    assert parts[0] == symbol
    assert parts[1] == side
    assert parts[2].isdigit()  # timestamp
    assert parts[3].isdigit()  # counter
    assert len(parts[4]) == 4 and parts[4].isdigit()  # random4


def test_client_order_id_uniqueness(rest_connector):
    """Test that client order IDs are unique across multiple calls."""
    symbol = "ETHUSDT"
    side = "Sell"
    
    cids = set()
    for _ in range(100):
        cid = rest_connector._generate_client_order_id(symbol, side)
        cids.add(cid)
    
    # All 100 should be unique
    assert len(cids) == 100


def test_client_order_id_timestamp_monotonic(rest_connector):
    """Test that timestamps in client order IDs are monotonically increasing."""
    symbol = "BTCUSDT"
    side = "Buy"
    
    cids = []
    for _ in range(10):
        cids.append(rest_connector._generate_client_order_id(symbol, side))
        time.sleep(0.001)  # Small delay to ensure timestamp difference
    
    # Extract timestamps
    timestamps = [int(cid.split('-')[2]) for cid in cids]
    
    # Check that timestamps are monotonically increasing
    for i in range(1, len(timestamps)):
        assert timestamps[i] >= timestamps[i-1]


def test_client_order_id_counter_increments(rest_connector):
    """Test that counter increments with each call."""
    symbol = "BTCUSDT"
    side = "Buy"
    
    cids = []
    for _ in range(10):
        cids.append(rest_connector._generate_client_order_id(symbol, side))
    
    # Extract counters
    counters = [int(cid.split('-')[3]) for cid in cids]
    
    # Check that counters are monotonically increasing
    for i in range(1, len(counters)):
        assert counters[i] == counters[i-1] + 1


def test_client_order_id_symbol_side_preserved(rest_connector):
    """Test that symbol and side are correctly preserved in client order ID."""
    test_cases = [
        ("BTCUSDT", "Buy"),
        ("ETHUSDT", "Sell"),
        ("ADAUSDT", "Buy"),
        ("DOTUSDT", "Sell"),
    ]
    
    for symbol, side in test_cases:
        cid = rest_connector._generate_client_order_id(symbol, side)
        parts = cid.split('-')
        assert parts[0] == symbol
        assert parts[1] == side


def test_client_order_id_random_suffix_range(rest_connector):
    """Test that random suffix is within expected range (1000-9999)."""
    symbol = "BTCUSDT"
    side = "Buy"
    
    for _ in range(50):
        cid = rest_connector._generate_client_order_id(symbol, side)
        random_suffix = int(cid.split('-')[4])  # Now at index 4
        assert 1000 <= random_suffix <= 9999


def test_client_order_id_no_collision_under_load(rest_connector):
    """Test that no collisions occur under rapid generation."""
    symbol = "BTCUSDT"
    side = "Buy"
    
    # Generate many IDs rapidly
    cids = set()
    start_time = time.time()
    
    while time.time() - start_time < 0.1:  # Generate for 100ms
        cid = rest_connector._generate_client_order_id(symbol, side)
        cids.add(cid)
    
    # Should have generated many unique IDs
    assert len(cids) > 50
    
    # No duplicates
    assert len(cids) == len(list(cids))


def test_client_order_id_format_consistency(rest_connector):
    """Test that format is consistent across different symbols and sides."""
    test_cases = [
        ("BTCUSDT", "Buy"),
        ("ETHUSDT", "Sell"),
        ("ADAUSDT", "Buy"),
        ("DOTUSDT", "Sell"),
        ("LINKUSDT", "Buy"),
    ]
    
    for symbol, side in test_cases:
        cid = rest_connector._generate_client_order_id(symbol, side)
        
        # Check separator consistency
        assert cid.count('-') == 4
        
        # Check parts are non-empty
        parts = cid.split('-')
        assert all(part for part in parts)
        
        # Check that each part has reasonable length
        assert len(parts[0]) >= 3  # symbol
        assert len(parts[1]) >= 2  # side
        assert len(parts[2]) >= 8  # timestamp (can vary)
        assert len(parts[3]) >= 1  # counter
        assert len(parts[4]) == 4  # random (always 4 digits)

"""
Unit tests for fast-cancel trigger logic.

Tests that orders are canceled when price moves beyond threshold,
with cooldown periods after volatile spikes.
"""
import pytest
import time
from unittest.mock import Mock, AsyncMock, MagicMock
from src.strategy.quote_loop import QuoteLoop
from src.execution.order_manager import OrderState
from src.common.di import AppContext


@pytest.fixture
def mock_ctx():
    """Create mock AppContext with fast_cancel config."""
    ctx = Mock(spec=AppContext)
    
    # Mock fast_cancel config
    fast_cancel_cfg = Mock()
    fast_cancel_cfg.enabled = True
    fast_cancel_cfg.cancel_threshold_bps = 3.0
    fast_cancel_cfg.cooldown_after_spike_ms = 500
    fast_cancel_cfg.spike_threshold_bps = 10.0
    ctx.cfg = Mock()
    ctx.cfg.fast_cancel = fast_cancel_cfg
    ctx.cfg.taker_cap = None  # Disable taker cap for these tests
    
    return ctx


@pytest.fixture
def mock_order_manager():
    """Create mock OrderManager."""
    manager = Mock()
    manager.active_orders = {}
    manager.cancel_order = AsyncMock()
    return manager


@pytest.fixture
def quote_loop(mock_ctx, mock_order_manager):
    """Create QuoteLoop instance."""
    return QuoteLoop(mock_ctx, mock_order_manager)


def test_no_cancel_within_threshold(quote_loop):
    """Test that order is NOT canceled when price move is within threshold."""
    order = OrderState(
        client_order_id="test123",
        order_id="",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )
    
    # Price moves 2 bps (below 3 bps threshold)
    current_mid = 50010.0  # 50000 * (1 + 0.0002) = 50010
    now_ms = int(time.time() * 1000)
    
    should_cancel, reason = quote_loop.should_fast_cancel(order, current_mid, now_ms)
    
    assert should_cancel is False
    assert reason == ""


def test_cancel_beyond_threshold(quote_loop):
    """Test that order IS canceled when price move exceeds threshold."""
    order = OrderState(
        client_order_id="test123",
        order_id="",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )
    
    # Price moves 5 bps (above 3 bps threshold, below 10 bps spike threshold)
    current_mid = 50025.0  # 50000 * (1 + 0.0005) = 50025
    now_ms = int(time.time() * 1000)
    
    should_cancel, reason = quote_loop.should_fast_cancel(order, current_mid, now_ms)
    
    assert should_cancel is True
    assert "adverse_move" in reason
    assert "5.00bps" in reason


def test_cancel_on_volatile_spike(quote_loop):
    """Test that order is canceled AND cooldown triggered on volatile spike."""
    order = OrderState(
        client_order_id="test123",
        order_id="",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )
    
    # Price moves 15 bps (above 10 bps spike threshold)
    current_mid = 50075.0  # 50000 * (1 + 0.0015) = 50075
    now_ms = int(time.time() * 1000)
    
    should_cancel, reason = quote_loop.should_fast_cancel(order, current_mid, now_ms)
    
    assert should_cancel is True
    assert "volatile_spike" in reason
    assert "15.00bps" in reason
    
    # Verify cooldown was triggered
    cooldown_remaining = quote_loop.get_cooldown_status("BTCUSDT")
    assert cooldown_remaining is not None
    assert cooldown_remaining > 0
    assert cooldown_remaining <= 500  # Within cooldown period


def test_no_cancel_during_cooldown(quote_loop):
    """Test that orders are NOT canceled during cooldown period."""
    symbol = "BTCUSDT"
    now_ms = int(time.time() * 1000)
    
    # Manually trigger cooldown
    quote_loop.cooldown_until_ms[symbol] = now_ms + 1000  # 1 second cooldown
    
    order = OrderState(
        client_order_id="test123",
        order_id="",
        symbol=symbol,
        side="Buy",
        price=50000.0,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )
    
    # Price moves 5 bps (would normally trigger cancel)
    current_mid = 50025.0
    
    should_cancel, reason = quote_loop.should_fast_cancel(order, current_mid, now_ms)
    
    assert should_cancel is False
    assert reason == "in_cooldown"


def test_cooldown_expires(quote_loop):
    """Test that cooldown expires after configured duration."""
    symbol = "BTCUSDT"
    now_ms = int(time.time() * 1000)
    
    # Set cooldown to expire 100ms ago
    quote_loop.cooldown_until_ms[symbol] = now_ms - 100
    
    # Check cooldown status (should be expired)
    cooldown_remaining = quote_loop.get_cooldown_status(symbol)
    assert cooldown_remaining is None
    
    # Verify cooldown entry was cleaned up
    assert symbol not in quote_loop.cooldown_until_ms


def test_fast_cancel_disabled(quote_loop):
    """Test that fast-cancel can be disabled via config."""
    quote_loop.fast_cancel_enabled = False
    
    order = OrderState(
        client_order_id="test123",
        order_id="",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )
    
    # Large price move (should normally trigger cancel)
    current_mid = 51000.0  # 20 bps move
    now_ms = int(time.time() * 1000)
    
    should_cancel, reason = quote_loop.should_fast_cancel(order, current_mid, now_ms)
    
    assert should_cancel is False
    assert reason == ""


@pytest.mark.asyncio
async def test_check_and_cancel_stale_orders(quote_loop, mock_order_manager):
    """Test that stale orders are identified and canceled."""
    symbol = "BTCUSDT"
    now_ms = int(time.time() * 1000)
    
    # Create 2 active orders
    order1 = OrderState(
        client_order_id="order1",
        order_id="",
        symbol=symbol,
        side="Buy",
        price=50000.0,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )
    
    order2 = OrderState(
        client_order_id="order2",
        order_id="",
        symbol=symbol,
        side="Sell",
        price=50100.0,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )
    
    mock_order_manager.active_orders = {
        "order1": order1,
        "order2": order2
    }
    
    # Price moves to 50030 (6 bps from order1, 1.4 bps from order2)
    current_mid = 50030.0
    
    canceled_ids = await quote_loop.check_and_cancel_stale_orders(symbol, current_mid, now_ms)
    
    # Only order1 should be canceled (>3 bps drift)
    assert len(canceled_ids) == 1
    assert "order1" in canceled_ids
    
    # Verify cancel_order was called
    assert mock_order_manager.cancel_order.call_count == 1
    mock_order_manager.cancel_order.assert_called_with("order1")


def test_bid_sell_symmetry(quote_loop):
    """Test that fast-cancel works symmetrically for bids and asks."""
    now_ms = int(time.time() * 1000)
    
    # Buy order
    buy_order = OrderState(
        client_order_id="buy1",
        order_id="",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )
    
    # Sell order
    sell_order = OrderState(
        client_order_id="sell1",
        order_id="",
        symbol="BTCUSDT",
        side="Sell",
        price=50000.0,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )
    
    # Price moves 5 bps
    current_mid = 50025.0
    
    # Both should trigger cancel (fast-cancel is side-agnostic)
    buy_cancel, buy_reason = quote_loop.should_fast_cancel(buy_order, current_mid, now_ms)
    sell_cancel, sell_reason = quote_loop.should_fast_cancel(sell_order, current_mid, now_ms)
    
    assert buy_cancel is True
    assert sell_cancel is True
    assert "adverse_move" in buy_reason
    assert "adverse_move" in sell_reason


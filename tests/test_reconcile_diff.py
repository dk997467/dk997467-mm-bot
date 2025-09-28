"""
Test order reconciliation logic and state synchronization.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from src.execution.reconcile import (
    OrderReconciler, OrderState, ReconciliationAction, ReconciliationResult
)
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
def mock_rest_connector():
    """Create mock REST connector."""
    connector = Mock(spec=BybitRESTConnector)
    connector.get_active_orders = AsyncMock()
    connector.get_order_history = AsyncMock()
    connector.cancel_order = AsyncMock()
    return connector


@pytest.fixture
def reconciler(mock_ctx, mock_rest_connector):
    """Create OrderReconciler instance."""
    return OrderReconciler(mock_ctx, mock_rest_connector)


@pytest.fixture
def sample_local_orders():
    """Create sample local orders for testing."""
    return {
        "BTCUSDT-Buy-1234567890-1-1000": OrderState(
            order_id="order_1",
            client_order_id="BTCUSDT-Buy-1234567890-1-1000",
            symbol="BTCUSDT",
            side="Buy",
            price=50000.0,
            qty=0.1,
            status="New",
            filled_qty=0.0,
            remaining_qty=0.1,
            created_time=1234567890.0,
            last_update_time=1234567890.0
        ),
        "BTCUSDT-Sell-1234567891-2-2000": OrderState(
            order_id="order_2",
            client_order_id="BTCUSDT-Sell-1234567891-2-2000",
            symbol="BTCUSDT",
            side="Sell",
            price=51000.0,
            qty=0.05,
            status="PartiallyFilled",
            filled_qty=0.02,
            remaining_qty=0.03,
            created_time=1234567891.0,
            last_update_time=1234567891.0
        )
    }


@pytest.fixture
def sample_exchange_orders():
    """Create sample exchange orders for testing."""
    return {
        "BTCUSDT-Buy-1234567890-1-1000": OrderState(
            order_id="order_1",
            client_order_id="BTCUSDT-Buy-1234567890-1-1000",
            symbol="BTCUSDT",
            side="Buy",
            price=50000.0,
            qty=0.1,
            status="Filled",
            filled_qty=0.1,
            remaining_qty=0.0,
            created_time=1234567890.0,
            last_update_time=1234567890.0
        ),
        "ETHUSDT-Buy-1234567892-3-3000": OrderState(
            order_id="order_3",
            client_order_id="ETHUSDT-Buy-1234567892-3-3000",
            symbol="ETHUSDT",
            side="Buy",
            price=3000.0,
            qty=1.0,
            status="New",
            filled_qty=0.0,
            remaining_qty=1.0,
            created_time=1234567892.0,
            last_update_time=1234567892.0
        )
    }


def test_reconciler_initialization(reconciler):
    """Test reconciler initialization."""
    assert reconciler.reconciliation_interval == 25
    assert reconciler.max_recent_history == 100
    assert reconciler.hard_desync_threshold == 0.1
    assert reconciler.risk_paused_tmp is False
    assert len(reconciler.local_orders) == 0


def test_add_local_order(reconciler):
    """Test adding order to local tracking."""
    order = OrderState(
        order_id="test_order",
        client_order_id="test_cid",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.1,
        status="New",
        filled_qty=0.0,
        remaining_qty=0.1,
        created_time=1234567890.0,
        last_update_time=1234567890.0
    )
    
    reconciler.add_local_order(order)
    assert "test_cid" in reconciler.local_orders
    assert reconciler.local_orders["test_cid"] == order


def test_remove_local_order(reconciler, sample_local_orders):
    """Test removing order from local tracking."""
    reconciler.local_orders = sample_local_orders.copy()
    
    cid = "BTCUSDT-Buy-1234567890-1-1000"
    reconciler.remove_local_order(cid)
    
    assert cid not in reconciler.local_orders
    assert len(reconciler.local_orders) == 1


def test_parse_exchange_order_valid():
    """Test parsing valid exchange order data."""
    order_data = {
        "orderId": "order_123",
        "orderLinkId": "BTCUSDT-Buy-1234567890-1-1000",
        "symbol": "BTCUSDT",
        "side": "Buy",
        "price": "50000.0",
        "qty": "0.1",
        "orderStatus": "New",
        "cumExecQty": "0.0",
        "createdTime": "1234567890000",
        "updatedTime": "1234567890000"
    }
    
    reconciler = OrderReconciler(Mock(), Mock())
    order = reconciler._parse_exchange_order(order_data)
    
    assert order is not None
    assert order.order_id == "order_123"
    assert order.client_order_id == "BTCUSDT-Buy-1234567890-1-1000"
    assert order.price == 50000.0
    assert order.qty == 0.1
    assert order.status == "New"


def test_parse_exchange_order_invalid():
    """Test parsing invalid exchange order data."""
    order_data = {
        "orderId": "order_123",
        # Missing required fields
    }
    
    reconciler = OrderReconciler(Mock(), Mock())
    order = reconciler._parse_exchange_order(order_data)
    
    assert order is None


@pytest.mark.asyncio
async def test_reconcile_orders_filled_order(reconciler, sample_local_orders, sample_exchange_orders):
    """Test reconciliation when local order is filled on exchange."""
    reconciler.local_orders = sample_local_orders.copy()
    
    # Local order is "New" but exchange shows "Filled"
    result = await reconciler._reconcile_orders(sample_exchange_orders, {})
    
    assert ReconciliationAction.MARK_FILLED in result.actions_taken
    assert ReconciliationAction.CLOSE_ORPHAN in result.actions_taken
    assert result.orders_fixed == 2  # 1 filled + 1 orphan
    assert result.orphans_closed == 1
    
    # Check that local order was updated
    local_order = reconciler.local_orders["BTCUSDT-Buy-1234567890-1-1000"]
    assert local_order.status == "Filled"
    assert local_order.filled_qty == 0.1
    assert local_order.remaining_qty == 0.0


@pytest.mark.asyncio
async def test_reconcile_orders_orphan_detection(reconciler, sample_local_orders, sample_exchange_orders):
    """Test detection and handling of orphaned exchange orders."""
    reconciler.local_orders = sample_local_orders.copy()
    
    # Exchange has an order not in local tracking
    result = await reconciler._reconcile_orders(sample_exchange_orders, {})
    
    assert ReconciliationAction.CLOSE_ORPHAN in result.actions_taken
    assert result.orphans_closed == 1


@pytest.mark.asyncio
async def test_reconcile_orders_hard_desync(reconciler):
    """Test hard desync detection and risk management pause."""
    # Create many local orders
    for i in range(20):
        order = OrderState(
            order_id=f"order_{i}",
            client_order_id=f"cid_{i}",
            symbol="BTCUSDT",
            side="Buy",
            price=50000.0 + i,
            qty=0.1,
            status="New",
            filled_qty=0.0,
            remaining_qty=0.1,
            created_time=1234567890.0,
            last_update_time=1234567890.0
        )
        reconciler.local_orders[f"cid_{i}"] = order
    
    # Exchange has very few orders (hard desync)
    exchange_orders = {}
    
    result = await reconciler._reconcile_orders(exchange_orders, {})
    
    assert ReconciliationAction.PAUSE_QUOTING in result.actions_taken
    assert result.hard_desync_detected is True
    assert reconciler.risk_paused_tmp is True


def test_should_update_local_state():
    """Test logic for determining when local state should be updated."""
    reconciler = OrderReconciler(Mock(), Mock())
    
    local = OrderState(
        order_id="order_1",
        client_order_id="cid_1",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.1,
        status="New",
        filled_qty=0.0,
        remaining_qty=0.1,
        created_time=1234567890.0,
        last_update_time=1234567890.0
    )
    
    # Different status
    exchange_status = OrderState(
        order_id="order_1",
        client_order_id="cid_1",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.1,
        status="PartiallyFilled",
        filled_qty=0.05,
        remaining_qty=0.05,
        created_time=1234567890.0,
        last_update_time=1234567890.0
    )
    
    assert reconciler._should_update_local_state(local, exchange_status) is True
    
    # Same state
    exchange_same = OrderState(
        order_id="order_1",
        client_order_id="cid_1",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.1,
        status="New",
        filled_qty=0.0,
        remaining_qty=0.1,
        created_time=1234567890.0,
        last_update_time=1234567890.0
    )
    
    assert reconciler._should_update_local_state(local, exchange_same) is False


def test_mark_order_filled(reconciler):
    """Test marking order as filled."""
    order = OrderState(
        order_id="order_1",
        client_order_id="cid_1",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.1,
        status="New",
        filled_qty=0.0,
        remaining_qty=0.1,
        created_time=1234567890.0,
        last_update_time=1234567890.0
    )
    
    reconciler._mark_order_filled(order)
    
    assert order.status == "Filled"
    assert order.filled_qty == 0.1
    assert order.remaining_qty == 0.0


def test_mark_order_cancelled(reconciler):
    """Test marking order as cancelled."""
    order = OrderState(
        order_id="order_1",
        client_order_id="cid_1",
        symbol="BTCUSDT",
        side="Buy",
        price=50000.0,
        qty=0.1,
        status="New",
        filled_qty=0.0,
        remaining_qty=0.1,
        created_time=1234567890.0,
        last_update_time=1234567890.0
    )
    
    reconciler._mark_order_cancelled(order)
    
    assert order.status == "Cancelled"


def test_risk_management_pause_resume(reconciler):
    """Test risk management pause and resume functionality."""
    assert reconciler.risk_paused_tmp is False
    
    reconciler._pause_risk_management("Test pause")
    assert reconciler.risk_paused_tmp is True
    assert reconciler.risk_pause_reason == "Test pause"
    
    reconciler._resume_risk_management()
    assert reconciler.risk_paused_tmp is False
    assert reconciler.risk_pause_reason == ""


def test_get_local_order(reconciler, sample_local_orders):
    """Test retrieving local order by client order ID."""
    reconciler.local_orders = sample_local_orders.copy()
    
    order = reconciler.get_local_order("BTCUSDT-Buy-1234567890-1-1000")
    assert order is not None
    assert order.symbol == "BTCUSDT"
    assert order.side == "Buy"
    
    # Non-existent order
    order = reconciler.get_local_order("non_existent")
    assert order is None

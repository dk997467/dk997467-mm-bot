"""
Test amend-first logic with fallback to cancel+create.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from src.execution.order_manager import OrderManager, OrderUpdateRequest
from src.connectors.bybit_rest import BybitRESTConnector
from src.execution.reconcile import OrderState
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
    connector.place_order = AsyncMock(return_value={'retCode': 0, 'result': {'orderLinkId': 'BTCUSDT-Buy-1234567890-1-1000'}})
    connector.cancel_order = AsyncMock(return_value={'retCode': 0, 'result': 'success'})
    connector.amend_order = AsyncMock(return_value={'retCode': 0, 'result': 'success'})
    
    # Mock rounding methods
    connector._round_to_tick = Mock(side_effect=lambda price, symbol: round(price / 0.1) * 0.1)  # BTC tick size
    connector._round_to_lot = Mock(side_effect=lambda qty, symbol: round(qty / 0.001) * 0.001)   # BTC lot size
    
    return connector


@pytest.fixture
def order_manager(mock_ctx, mock_rest_connector):
    """Create OrderManager instance."""
    return OrderManager(mock_ctx, mock_rest_connector)


@pytest.fixture
def sample_order():
    """Create sample order for testing."""
    return OrderState(
        order_id="order_123",
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
    )


def test_can_amend_order_eligible(order_manager, sample_order):
    """Test that eligible orders can be amended."""
    # Order has been in book long enough and changes are within thresholds
    # new_price = 50000.5 rounds to 50000.5 (0.001% change, within 1 bps threshold)
    # new_qty = 0.11 rounds to 0.11 (10% change, within 20% threshold)
    new_price = 50000.5
    new_qty = 0.11
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):  # 1 second later
        can_amend = order_manager._can_amend_order(sample_order, new_price, new_qty)
        assert can_amend is True


def test_can_amend_order_too_soon(order_manager, sample_order):
    """Test that orders cannot be amended if they haven't been in book long enough."""
    new_price = 50100.0
    new_qty = 0.11
    
    # Mock time to make order ineligible (too soon)
    with patch('time.time', return_value=1234567890.0 + 0.1):  # 100ms later
        can_amend = order_manager._can_amend_order(sample_order, new_price, new_qty)
        assert can_amend is False


def test_can_amend_order_price_change_too_large(order_manager, sample_order):
    """Test that orders cannot be amended if price change exceeds threshold."""
    # new_price = 51000.0 rounds to 51000.0 (2% change = 200 bps, exceeds 1 bps threshold)
    new_price = 51000.0
    new_qty = 0.11
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        can_amend = order_manager._can_amend_order(sample_order, new_price, new_qty)
        assert can_amend is False


def test_can_amend_order_qty_change_too_large(order_manager, sample_order):
    """Test that orders cannot be amended if quantity change exceeds threshold."""
    # new_price = 50100.0 rounds to 50100.0 (0.2% change = 2 bps, exceeds 1 bps threshold)
    # new_qty = 0.15 rounds to 0.15 (50% change, exceeds 20% threshold)
    new_price = 50100.0
    new_qty = 0.15
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        can_amend = order_manager._can_amend_order(sample_order, new_price, new_qty)
        assert can_amend is False


@pytest.mark.asyncio
async def test_update_order_amend_success(order_manager, sample_order):
    """Test successful order update using amend."""
    # Add order to tracking
    order_manager.active_orders[sample_order.client_order_id] = sample_order
    order_manager.reconciler.add_local_order(sample_order)
    
    # Mock successful amend (already configured in fixture)
    mock_rest_connector = order_manager.rest_connector
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        result = await order_manager.update_order(
            sample_order.client_order_id,
            new_price=50000.5  # Very small change
        )
    
    assert result is True
    
    # Should have called amend, not cancel+create
    mock_rest_connector.amend_order.assert_called_once()
    mock_rest_connector.cancel_order.assert_not_called()
    mock_rest_connector.place_order.assert_not_called()
    
    # Check that local state was updated with rounded values
    updated_order = order_manager.active_orders[sample_order.client_order_id]
    # 50000.5 rounds to 50000.5 (BTC tick size is 0.1)
    assert updated_order.price == 50000.5


@pytest.mark.asyncio
async def test_update_order_amend_failure_fallback(order_manager, sample_order):
    """Test order update with amend failure and fallback to cancel+create."""
    # Add order to tracking
    order_manager.active_orders[sample_order.client_order_id] = sample_order
    order_manager.reconciler.add_local_order(sample_order)
    
    # Mock amend failure, then successful cancel+create
    mock_rest_connector = order_manager.rest_connector
    mock_rest_connector.amend_order.side_effect = Exception("Amend failed")
    # cancel_order and place_order already configured in fixture
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        result = await order_manager.update_order(
            sample_order.client_order_id,
            new_price=50000.5  # Very small change
        )
    
    assert result is True
    
    # Should have tried amend first, then fallback
    mock_rest_connector.amend_order.assert_called_once()
    mock_rest_connector.cancel_order.assert_called_once()
    mock_rest_connector.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_update_order_ineligible_goes_direct_to_cancel_create(order_manager, sample_order):
    """Test that ineligible orders go directly to cancel+create."""
    # Add order to tracking
    order_manager.active_orders[sample_order.client_order_id] = sample_order
    order_manager.reconciler.add_local_order(sample_order)
    
    # Mock successful cancel+create (already configured in fixture)
    mock_rest_connector = order_manager.rest_connector
    
    # Mock time to make order ineligible (too soon)
    with patch('time.time', return_value=1234567890.0 + 0.1):
        result = await order_manager.update_order(
            sample_order.client_order_id,
            new_price=50000.5  # Very small change
        )
    
    assert result is True
    
    # Should have gone directly to cancel+create
    mock_rest_connector.amend_order.assert_not_called()
    mock_rest_connector.cancel_order.assert_called_once()
    mock_rest_connector.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_update_order_cancel_create_failure(order_manager, sample_order):
    """Test order update when cancel+create fails."""
    # Add order to tracking
    order_manager.active_orders[sample_order.client_order_id] = sample_order
    order_manager.reconciler.add_local_order(sample_order)
    
    # Mock amend failure and cancel+create failure
    mock_rest_connector = order_manager.rest_connector
    mock_rest_connector.amend_order.side_effect = Exception("Amend failed")
    mock_rest_connector.cancel_order.side_effect = Exception("Cancel failed")
    # place_order already configured in fixture
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        result = await order_manager.update_order(
            sample_order.client_order_id,
            new_price=50000.5  # Very small change
        )
    
    assert result is False
    
    # Should have tried both approaches
    mock_rest_connector.amend_order.assert_called_once()
    mock_rest_connector.cancel_order.assert_called_once()


@pytest.mark.asyncio
async def test_update_order_price_only(order_manager, sample_order):
    """Test order update with price change only."""
    # Add order to tracking
    order_manager.active_orders[sample_order.client_order_id] = sample_order
    order_manager.reconciler.add_local_order(sample_order)
    
    # Mock successful amend (already configured in fixture)
    mock_rest_connector = order_manager.rest_connector
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        result = await order_manager.update_order(
            sample_order.client_order_id,
            new_price=50000.5  # Very small change
        )
    
    assert result is True
    
    # Should have called amend with price only
    mock_rest_connector.amend_order.assert_called_once_with(
        symbol=sample_order.symbol,
        client_order_id=sample_order.client_order_id,
        price=50000.5,
        qty=None
    )


@pytest.mark.asyncio
async def test_update_order_qty_only(order_manager, sample_order):
    """Test order update with quantity change only."""
    # Add order to tracking
    order_manager.active_orders[sample_order.client_order_id] = sample_order
    order_manager.reconciler.add_local_order(sample_order)
    
    # Mock successful amend (already configured in fixture)
    mock_rest_connector = order_manager.rest_connector
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        result = await order_manager.update_order(
            sample_order.client_order_id,
            new_qty=0.11  # 10% change (within 20% threshold)
        )
    
    assert result is True
    
    # Should have called amend with qty only
    mock_rest_connector.amend_order.assert_called_once_with(
        symbol=sample_order.symbol,
        client_order_id=sample_order.client_order_id,
        price=None,
        qty=0.11
    )


@pytest.mark.asyncio
async def test_update_order_both_price_and_qty(order_manager, sample_order):
    """Test order update with both price and quantity changes."""
    # Add order to tracking
    order_manager.active_orders[sample_order.client_order_id] = sample_order
    order_manager.reconciler.add_local_order(sample_order)
    
    # Mock successful amend (already configured in fixture)
    mock_rest_connector = order_manager.rest_connector
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        result = await order_manager.update_order(
            sample_order.client_order_id,
            new_price=50000.5,  # Very small change
            new_qty=0.11  # 10% change (within 20% threshold)
        )
    
    assert result is True
    
    # Should have called amend with both price and qty
    mock_rest_connector.amend_order.assert_called_once_with(
        symbol=sample_order.symbol,
        client_order_id=sample_order.client_order_id,
        price=50000.5,
        qty=0.11
    )


def test_order_not_found_error(order_manager):
    """Test error when trying to update non-existent order."""
    with pytest.raises(ValueError, match="Order non_existent not found"):
        asyncio.run(order_manager.update_order("non_existent", new_price=50000.5))


@pytest.mark.asyncio
async def test_update_order_metrics_increment(order_manager, sample_order):
    """Test that metrics are incremented on successful amend."""
    # Add order to tracking
    order_manager.active_orders[sample_order.client_order_id] = sample_order
    order_manager.reconciler.add_local_order(sample_order)
    
    # Mock metrics
    mock_metrics = Mock()
    order_manager.metrics = mock_metrics
    
    # Mock successful amend (already configured in fixture)
    mock_rest_connector = order_manager.rest_connector
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        await order_manager.update_order(
            sample_order.client_order_id,
            new_price=50000.5  # Very small change
        )
    
    # Should have incremented replace metrics
    mock_metrics.replaces_total.labels.assert_called_with(symbol=sample_order.symbol)
    mock_metrics.replaces_total.labels().inc.assert_called_once()


@pytest.mark.asyncio
async def test_update_order_state_tracking(order_manager, sample_order):
    """Test that order state is properly tracked during updates."""
    # Add order to tracking
    order_manager.active_orders[sample_order.client_order_id] = sample_order
    order_manager.reconciler.add_local_order(sample_order)
    
    # Mock successful amend (already configured in fixture)
    mock_rest_connector = order_manager.rest_connector
    
    # Mock time to make order eligible
    with patch('time.time', return_value=1234567890.0 + 1.0):
        await order_manager.update_order(
            sample_order.client_order_id,
            new_price=50000.5,  # Very small change
            new_qty=0.11  # 10% change (within 20% threshold)
        )
    
    # Check that local state was updated
    updated_order = order_manager.active_orders[sample_order.client_order_id]
    assert updated_order.price == 50000.5
    assert updated_order.qty == 0.11
    assert updated_order.remaining_qty == 0.11  # Should be recalculated
    
    # Check that reconciliation state was also updated
    reconciled_order = order_manager.reconciler.get_local_order(sample_order.client_order_id)
    assert reconciled_order.price == 50000.5
    assert reconciled_order.qty == 0.11

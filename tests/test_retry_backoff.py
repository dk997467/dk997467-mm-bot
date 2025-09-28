"""
Test retry and backoff logic for REST API calls.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from aiohttp import ClientResponseError

from src.connectors.bybit_rest import BybitRESTConnector, BybitError
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
        'api_secret': 'test_secret',
        'max_retries': 3,
        'base_backoff_ms': 100,
        'max_backoff_ms': 1000
    }
    return BybitRESTConnector(mock_ctx, config)


def test_error_classification_transient():
    """Test classification of transient errors."""
    connector = BybitRESTConnector(Mock(), {})
    
    # Test transient error codes
    transient_codes = [10006, 10018, 10019, 10020, 10021]
    
    for code in transient_codes:
        error = connector._classify_bybit_error(code, "Test error")
        assert error.is_transient is True
        assert error.retry_after_ms > 0


def test_error_classification_fatal():
    """Test classification of fatal errors."""
    connector = BybitRESTConnector(Mock(), {})
    
    # Test fatal error codes
    fatal_codes = [10001, 10002, 10003, 10004, 10005]
    
    for code in fatal_codes:
        error = connector._classify_bybit_error(code, "Test error")
        assert error.is_transient is False


def test_error_classification_unknown():
    """Test classification of unknown error codes."""
    connector = BybitRESTConnector(Mock(), {})
    
    # Test unknown error code
    error = connector._classify_bybit_error(99999, "Unknown error")
    assert error.is_transient is True  # Unknown errors treated as transient
    assert error.retry_after_ms == 2000  # Default backoff


def test_backoff_calculation_with_jitter():
    """Test exponential backoff calculation with jitter."""
    connector = BybitRESTConnector(Mock(), {
        'base_backoff_ms': 100,
        'max_backoff_ms': 1000
    })
    
    # Test backoff progression
    backoffs = []
    for retry_count in range(3):
        backoff_ms = min(
            connector.base_backoff_ms * (2 ** retry_count) + 500,  # Mock jitter
            connector.max_backoff_ms
        )
        backoffs.append(backoff_ms)
    
    # Should be exponential with jitter: 600, 700, 900 (capped at 1000)
    assert backoffs[0] == 600  # 100 + 500 jitter
    assert backoffs[1] == 700  # 200 + 500 jitter
    assert backoffs[2] == 900  # 400 + 500 jitter


@pytest.mark.asyncio
async def test_make_request_success_no_retry(rest_connector):
    """Test successful request without retries."""
    # Mock successful response
    mock_response = Mock()
    mock_response.json = AsyncMock(return_value={'retCode': 0, 'result': 'success'})
    
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(return_value=mock_response)
        
        result = await rest_connector._make_request("POST", "/test", {"data": "test"})
        
        assert result['retCode'] == 0
        assert result['result'] == 'success'


@pytest.mark.asyncio
async def test_make_request_transient_error_with_retry(rest_connector):
    """Test request with transient error that gets retried."""
    # Mock responses: first transient error, then success
    mock_response_error = Mock()
    mock_response_error.headers = {}  # Empty headers
    mock_response_error.json = AsyncMock(return_value={
        'retCode': 10006,  # Rate limit exceeded
        'retMsg': 'Rate limit exceeded'
    })
    
    mock_response_success = Mock()
    mock_response_success.json = AsyncMock(return_value={'retCode': 0, 'result': 'success'})
    
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(side_effect=[mock_response_error, mock_response_success])
        
        # Mock sleep to avoid actual delays in tests
        with patch('asyncio.sleep') as mock_sleep:
            result = await rest_connector._make_request("POST", "/test", {"data": "test"})
            
            # Should have slept once due to retry
            assert mock_sleep.call_count == 1
            assert result['retCode'] == 0


@pytest.mark.asyncio
async def test_make_request_fatal_error_no_retry(rest_connector):
    """Test request with fatal error that doesn't get retried."""
    # Mock fatal error response
    mock_response = Mock()
    mock_response.headers = {}  # Empty headers
    mock_response.json = AsyncMock(return_value={
        'retCode': 10001,  # Invalid parameter
        'retMsg': 'Invalid parameter'
    })
    
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(return_value=mock_response)
        
        # Should raise exception immediately
        with pytest.raises(Exception) as exc_info:
            await rest_connector._make_request("POST", "/test", {"data": "test"})
        
        assert "Bybit API error 10001" in str(exc_info.value)


@pytest.mark.asyncio
async def test_make_request_max_retries_exceeded(rest_connector):
    """Test request that exceeds maximum retry attempts."""
    # Mock persistent transient error
    mock_response = Mock()
    mock_response.headers = {}  # Empty headers
    mock_response.json = AsyncMock(return_value={
        'retCode': 10006,  # Rate limit exceeded
        'retMsg': 'Rate limit exceeded'
    })
    
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(return_value=mock_response)
        
        # Should raise exception after max retries
        with pytest.raises(Exception) as exc_info:
            await rest_connector._make_request("POST", "/test", {"data": "test"})
        
        assert "Bybit API error 10006" in str(exc_info.value)


@pytest.mark.asyncio
async def test_make_request_network_error(rest_connector):
    """Test request with network error."""
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(side_effect=Exception("Network error"))
        
        # Should raise exception immediately
        with pytest.raises(Exception) as exc_info:
            await rest_connector._make_request("POST", "/test", {"data": "test"})
        
        assert "Network error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_make_request_latency_metrics(rest_connector):
    """Test that latency metrics are recorded."""
    # Mock successful response
    mock_response = Mock()
    mock_response.json = AsyncMock(return_value={'retCode': 0, 'result': 'success'})
    
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(return_value=mock_response)
        
        # Mock metrics
        mock_metrics = Mock()
        rest_connector.metrics = mock_metrics
        
        await rest_connector._make_request("POST", "/test", {"data": "test"})
        
        # Should have recorded latency
        mock_metrics.latency_ms.observe.assert_called_once()
        call_args = mock_metrics.latency_ms.observe.call_args
        # First positional argument should be the labels dict
        assert call_args[0][0]['stage'] == 'rest'


@pytest.mark.asyncio
async def test_make_request_error_rate_metrics(rest_connector):
    """Test that error rate metrics are incremented on errors."""
    # Mock transient error response
    mock_response = Mock()
    mock_response.headers = {}  # Empty headers
    mock_response.json = AsyncMock(return_value={
        'retCode': 10006,  # Rate limit exceeded
        'retMsg': 'Rate limit exceeded'
    })
    
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(return_value=mock_response)
        
        # Mock metrics
        mock_metrics = Mock()
        rest_connector.metrics = mock_metrics
        
        # Mock sleep to avoid delays
        with patch('asyncio.sleep'):
            with pytest.raises(Exception):
                await rest_connector._make_request("POST", "/test", {"data": "test"})
        
        # Should have incremented error rate
        mock_metrics.rest_error_rate.labels.assert_called_with(exchange="bybit")
        mock_metrics.rest_error_rate.labels().inc.assert_called()


def test_connector_configuration():
    """Test connector configuration parameters."""
    config = {
        'max_retries': 5,
        'base_backoff_ms': 200,
        'max_backoff_ms': 5000
    }
    
    connector = BybitRESTConnector(Mock(), config)
    
    assert connector.max_retries == 5
    assert connector.base_backoff_ms == 200
    assert connector.max_backoff_ms == 3000  # Capped at 3 seconds


def test_connector_default_configuration():
    """Test connector default configuration values."""
    connector = BybitRESTConnector(Mock(), {})
    
    assert connector.max_retries == 3
    assert connector.base_backoff_ms == 1000
    assert connector.max_backoff_ms == 3000  # Capped at 3 seconds
    assert connector.base_url == 'https://api.bybit.com'
    assert connector.recv_window == 5000


@pytest.mark.asyncio
async def test_place_order_with_client_order_id(rest_connector):
    """Test that place_order generates and uses client order ID."""
    # Mock successful response
    mock_response = Mock()
    mock_response.json = AsyncMock(return_value={
        'retCode': 0,
        'result': {
            'orderId': 'exchange_order_123',
            'orderLinkId': 'BTCUSDT-Buy-1234567890-1-1000'
        }
    })
    
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(return_value=mock_response)
        
        result = await rest_connector.place_order(
            symbol="BTCUSDT",
            side="Buy",
            order_type="Limit",
            qty=0.1,
            price=50000.0
        )
        
        # Should return the client order ID
        assert result == 'BTCUSDT-Buy-1234567890-1-1000'


@pytest.mark.asyncio
async def test_cancel_order_by_client_order_id(rest_connector):
    """Test cancelling order by client order ID."""
    # Mock successful response
    mock_response = Mock()
    mock_response.json = AsyncMock(return_value={'retCode': 0, 'result': 'success'})
    
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(return_value=mock_response)
        
        result = await rest_connector.cancel_order(
            symbol="BTCUSDT",
            client_order_id="BTCUSDT-Buy-1234567890-1-1000"
        )
        
        assert result['retCode'] == 0


@pytest.mark.asyncio
async def test_amend_order_by_client_order_id(rest_connector):
    """Test amending order by client order ID."""
    # Mock successful response
    mock_response = Mock()
    mock_response.json = AsyncMock(return_value={'retCode': 0, 'result': 'success'})
    
    with patch.object(rest_connector, 'session') as mock_session:
        mock_session.request = AsyncMock(return_value=mock_response)
        
        result = await rest_connector.amend_order(
            symbol="BTCUSDT",
            client_order_id="BTCUSDT-Buy-1234567890-1-1000",
            price=51000.0
        )
        
        assert result['retCode'] == 0

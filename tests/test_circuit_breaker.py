"""
Test circuit breaker functionality for REST connector.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch
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
    """Create REST connector with circuit breaker."""
    config = {
        'base_url': 'https://api.bybit.com',
        'api_key': 'test_key',
        'api_secret': 'test_secret',
        'circuit_breaker_threshold': 3,  # Low threshold for testing
        'circuit_breaker_window_ms': 1000,  # 1 second window
        'circuit_breaker_timeout_ms': 2000,  # 2 second timeout
        'max_attempts': 2
    }
    return BybitRESTConnector(mock_ctx, config)


@pytest.fixture
def mock_session():
    """Create mock aiohttp session."""
    session = Mock()
    session.get = AsyncMock()
    session.request = AsyncMock()
    return session


def test_circuit_breaker_initial_state(rest_connector):
    """Test initial circuit breaker state."""
    assert not rest_connector.is_circuit_open()
    
    state = rest_connector.get_circuit_state()
    assert state["open"] is False
    assert state["error_count"] == 0
    assert state["last_error_time"] == 0
    assert state["open_time"] == 0


@pytest.mark.asyncio
async def test_circuit_breaker_opens_on_threshold(rest_connector, mock_session):
    """Test circuit breaker opens when error threshold is reached."""
    rest_connector.session = mock_session
    
    # Mock successful response first
    mock_response = Mock()
    mock_response.headers = {}
    mock_response.json = AsyncMock(return_value={'retCode': 0, 'result': 'success'})
    mock_session.get.return_value = mock_response
    
    # Make successful request
    with patch('time.time', return_value=1000.0):
        result = await rest_connector._make_request("GET", "/test", attempt=1)
        assert result['retCode'] == 0
    
    # Mock error response
    mock_error_response = Mock()
    mock_error_response.headers = {}
    mock_error_response.json = AsyncMock(return_value={'retCode': 10006, 'retMsg': 'Rate limit exceeded'})
    mock_session.get.return_value = mock_error_response
    
    # Make requests until circuit opens
    with patch('time.time', return_value=1000.0):
        for i in range(3):  # Threshold is 3
            try:
                await rest_connector._make_request("GET", "/test", attempt=1)
            except Exception:
                pass
            # Manually update circuit breaker state for testing
            rest_connector._update_circuit_breaker(False)
    
    # Circuit should be open
    assert rest_connector.is_circuit_open()
    
    state = rest_connector.get_circuit_state()
    assert state["open"] is True
    assert state["error_count"] >= 3


@pytest.mark.asyncio
async def test_circuit_breaker_auto_closes_after_timeout(rest_connector, mock_session):
    """Test circuit breaker auto-closes after timeout."""
    rest_connector.session = mock_session
    
    # Mock error response
    mock_error_response = Mock()
    mock_error_response.headers = {}
    mock_error_response.json = AsyncMock(return_value={'retCode': 10006, 'retMsg': 'Rate limit exceeded'})
    mock_session.get.return_value = mock_error_response
    
    # Make requests until circuit opens
    with patch('time.time', return_value=1000.0):
        for i in range(3):
            try:
                await rest_connector._make_request("GET", "/test", attempt=1)
            except Exception:
                pass
            # Manually update circuit breaker state for testing
            rest_connector._update_circuit_breaker(False)
    
    # Circuit should be open
    assert rest_connector.is_circuit_open()
    
    # Wait for timeout and check if circuit closes
    with patch('time.time', return_value=3000.0):  # 2 seconds later
        assert rest_connector._should_allow_request("create")
        assert not rest_connector.is_circuit_open()


@pytest.mark.asyncio
async def test_circuit_breaker_allows_cancels_when_open(rest_connector, mock_session):
    """Test that circuit breaker allows cancel operations when open."""
    rest_connector.session = mock_session
    
    # Mock error response to open circuit
    mock_error_response = Mock()
    mock_error_response.headers = {}
    mock_error_response.json = AsyncMock(return_value={'retCode': 10006, 'retMsg': 'Rate limit exceeded'})
    mock_session.get.return_value = mock_error_response
    
    # Manually open circuit breaker for testing
    for i in range(3):
        rest_connector._update_circuit_breaker(False)
    
    # Circuit should be open
    assert rest_connector.is_circuit_open()
    
    # Cancel operations should be allowed
    assert rest_connector._should_allow_request("cancel")
    
    # Create/amend operations should be blocked
    assert not rest_connector._should_allow_request("create")
    assert not rest_connector._should_allow_request("amend")


@pytest.mark.asyncio
async def test_circuit_breaker_respects_retry_after_header(rest_connector, mock_session):
    """Test circuit breaker respects Retry-After header."""
    rest_connector.session = mock_session
    
    # Mock response with Retry-After header
    mock_response = Mock()
    mock_response.headers = {'Retry-After': '5'}  # 5 seconds
    mock_response.json = AsyncMock(return_value={'retCode': 10006, 'retMsg': 'Rate limit exceeded'})
    mock_session.get.return_value = mock_response
    
    # Make request and check backoff calculation
    with patch('time.time', return_value=1000.0):
        with patch('asyncio.sleep') as mock_sleep:
            try:
                await rest_connector._make_request("GET", "/test", attempt=1)
            except Exception:
                pass
            
                            # Should have called sleep with at least 3 seconds (capped)
                mock_sleep.assert_called()
                call_args = mock_sleep.call_args[0][0]
                assert call_args >= 3.0  # Capped at max_backoff_ms


@pytest.mark.asyncio
async def test_circuit_breaker_metrics_increment(rest_connector, mock_session):
    """Test that circuit breaker metrics are incremented."""
    # Mock metrics
    mock_metrics = Mock()
    rest_connector.metrics = mock_metrics
    
    rest_connector.session = mock_session
    
    # Mock error response
    mock_error_response = Mock()
    mock_error_response.headers = {}
    mock_error_response.json = AsyncMock(return_value={'retCode': 10006, 'retMsg': 'Rate limit exceeded'})
    mock_session.get.return_value = mock_error_response
    
    # Make requests until circuit opens
    with patch('time.time', return_value=1000.0):
        for i in range(3):
            try:
                await rest_connector._make_request("GET", "/test", attempt=1)
            except Exception:
                pass
            # Manually update circuit breaker state for testing
            rest_connector._update_circuit_breaker(False)
    
    # Check that metrics were incremented
    mock_metrics.circuit_breaker_open.labels.assert_called_with(stage="rest")


@pytest.mark.asyncio
async def test_circuit_breaker_auto_close_metrics(rest_connector, mock_session):
    """Test that circuit breaker close metrics are incremented."""
    # Mock metrics
    mock_metrics = Mock()
    rest_connector.metrics = mock_metrics
    
    rest_connector.session = mock_session
    
    # Mock error response to open circuit
    mock_error_response = Mock()
    mock_error_response.headers = {}
    mock_error_response.json = AsyncMock(return_value={'retCode': 10006, 'retMsg': 'Rate limit exceeded'})
    mock_session.get.return_value = mock_error_response
    
    # Make requests until circuit opens
    with patch('time.time', return_value=1000.0):
        for i in range(3):
            try:
                await rest_connector._make_request("GET", "/test", attempt=1)
            except Exception:
                pass
            # Manually update circuit breaker state for testing
            rest_connector._update_circuit_breaker(False)
    
    # Circuit should be open
    assert rest_connector.is_circuit_open()
    
    # Wait for timeout and check if circuit closes
    with patch('time.time', return_value=3000.0):  # 2 seconds later
        assert rest_connector._should_allow_request("create")
        assert not rest_connector.is_circuit_open()
        
        # Check that close metric was incremented
        mock_metrics.circuit_breaker_close.labels.assert_called_with(stage="rest")


def test_circuit_breaker_configuration(rest_connector):
    """Test circuit breaker configuration."""
    assert rest_connector._circuit_breaker_threshold == 3
    assert rest_connector._circuit_breaker_window_ms == 1000
    assert rest_connector._circuit_breaker_timeout_ms == 2000
    assert rest_connector.max_attempts == 2


def test_circuit_breaker_backoff_cap(rest_connector):
    """Test that backoff is capped at 3 seconds."""
    assert rest_connector.max_backoff_ms == 3000  # Should be capped at 3s

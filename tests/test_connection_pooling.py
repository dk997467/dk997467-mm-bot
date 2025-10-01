"""
Tests for HTTP connection pooling in REST API connector.

Validates:
1. ConnectionPoolConfig validation
2. TCPConnector creation with proper settings
3. Connection reuse and pooling behavior
4. Metrics updates
"""

import pytest
import asyncio
from dataclasses import asdict
from unittest.mock import Mock, AsyncMock, MagicMock
import aiohttp

from src.common.config import ConnectionPoolConfig
from src.common.di import AppContext


def test_connection_pool_config_defaults():
    """Test ConnectionPoolConfig with default values."""
    config = ConnectionPoolConfig()
    
    assert config.limit == 100
    assert config.limit_per_host == 30
    assert config.connect_timeout == 10.0
    assert config.sock_read_timeout == 30.0
    assert config.total_timeout == 60.0
    assert config.ttl_dns_cache == 300
    assert config.keepalive_timeout == 30.0
    assert config.enable_cleanup_closed is True
    assert config.force_close is False


def test_connection_pool_config_validation():
    """Test ConnectionPoolConfig validation."""
    
    # Valid config
    valid_config = ConnectionPoolConfig(
        limit=50,
        limit_per_host=10,
        connect_timeout=5.0,
        sock_read_timeout=20.0,
        total_timeout=30.0
    )
    assert valid_config.limit == 50
    
    # Invalid: limit < 1
    with pytest.raises(ValueError, match="limit must be >= 1"):
        ConnectionPoolConfig(limit=0)
    
    # Invalid: limit_per_host > limit
    with pytest.raises(ValueError, match="limit_per_host must be between 1 and limit"):
        ConnectionPoolConfig(limit=10, limit_per_host=20)
    
    # Invalid: connect_timeout > total_timeout
    with pytest.raises(ValueError, match="connect_timeout must be"):
        ConnectionPoolConfig(connect_timeout=100.0, total_timeout=50.0)
    
    # Invalid: negative ttl_dns_cache
    with pytest.raises(ValueError, match="ttl_dns_cache must be >= 0"):
        ConnectionPoolConfig(ttl_dns_cache=-1)


@pytest.mark.asyncio
async def test_rest_connector_uses_connection_pool():
    """Test that REST connector creates TCPConnector with pool settings."""
    from src.connectors.bybit_rest import BybitRESTConnector
    from src.common.config import Config
    
    # Create mock context with connection pool config
    ctx = Mock(spec=AppContext)
    config_obj = Config()
    config_obj.connection_pool = ConnectionPoolConfig(
        limit=50,
        limit_per_host=10,
        keepalive_timeout=15.0
    )
    ctx.config = config_obj
    ctx.metrics = None
    
    connector_config = {
        'base_url': 'https://api-testnet.bybit.com',
        'api_key': 'test_key',
        'api_secret': 'test_secret'
    }
    
    connector = BybitRESTConnector(ctx, connector_config)
    
    # Enter context manager to initialize session
    async with connector:
        assert connector.session is not None
        assert connector.connected is True
        
        # Check that session has TCPConnector
        assert connector.session.connector is not None
        assert isinstance(connector.session.connector, aiohttp.TCPConnector)
        
        # Check connector settings
        tcp_connector = connector.session.connector
        assert tcp_connector.limit == 50
        assert tcp_connector.limit_per_host == 10
        assert tcp_connector.keepalive_timeout == 15.0
        assert tcp_connector.force_close is False
        assert tcp_connector.enable_cleanup_closed is True
    
    # Check that connection is closed after exit
    assert connector.connected is False


@pytest.mark.asyncio
async def test_rest_connector_timeout_configuration():
    """Test that REST connector configures timeouts correctly."""
    from src.connectors.bybit_rest import BybitRESTConnector
    from src.common.config import Config
    
    ctx = Mock(spec=AppContext)
    config_obj = Config()
    config_obj.connection_pool = ConnectionPoolConfig(
        connect_timeout=5.0,
        sock_read_timeout=15.0,
        total_timeout=30.0
    )
    ctx.config = config_obj
    ctx.metrics = None
    
    connector_config = {
        'base_url': 'https://api-testnet.bybit.com',
        'api_key': 'test_key',
        'api_secret': 'test_secret'
    }
    
    connector = BybitRESTConnector(ctx, connector_config)
    
    async with connector:
        # Check timeout settings
        timeout = connector.session.timeout
        assert timeout.total == 30.0
        assert timeout.connect == 5.0
        assert timeout.sock_read == 15.0


@pytest.mark.asyncio
async def test_update_pool_metrics():
    """Test that update_pool_metrics works correctly."""
    from src.connectors.bybit_rest import BybitRESTConnector
    from src.metrics.exporter import Metrics
    from src.common.config import Config
    
    # Create mock context with metrics
    ctx = Mock(spec=AppContext)
    config_obj = Config()
    config_obj.connection_pool = ConnectionPoolConfig()
    ctx.config = config_obj
    
    # Mock metrics
    mock_metrics = Mock(spec=Metrics)
    mock_metrics.http_pool_connections_limit = Mock()
    mock_metrics.http_pool_connections_limit.labels = Mock(return_value=Mock(set=Mock()))
    ctx.metrics = mock_metrics
    
    connector_config = {
        'base_url': 'https://api-testnet.bybit.com',
        'api_key': 'test_key',
        'api_secret': 'test_secret'
    }
    
    connector = BybitRESTConnector(ctx, connector_config)
    
    async with connector:
        # Call update_pool_metrics
        connector.update_pool_metrics()
        
        # Verify metrics were updated
        mock_metrics.http_pool_connections_limit.labels.assert_called_with(exchange='bybit')


def test_connection_pool_config_to_dict():
    """Test that ConnectionPoolConfig can be converted to dict."""
    config = ConnectionPoolConfig(
        limit=75,
        limit_per_host=15,
        keepalive_timeout=20.0
    )
    
    config_dict = asdict(config)
    assert config_dict['limit'] == 75
    assert config_dict['limit_per_host'] == 15
    assert config_dict['keepalive_timeout'] == 20.0


@pytest.mark.asyncio
async def test_connector_without_pool_config():
    """Test that connector works without ConnectionPoolConfig (uses defaults)."""
    from src.connectors.bybit_rest import BybitRESTConnector
    
    # Create minimal context without connection_pool config
    ctx = Mock(spec=AppContext)
    ctx.metrics = None
    # Don't set ctx.config to simulate missing config
    
    connector_config = {
        'base_url': 'https://api-testnet.bybit.com',
        'api_key': 'test_key',
        'api_secret': 'test_secret'
    }
    
    connector = BybitRESTConnector(ctx, connector_config)
    
    async with connector:
        # Should still work with default values
        assert connector.session is not None
        assert isinstance(connector.session.connector, aiohttp.TCPConnector)
        
        # Check defaults are applied
        tcp_connector = connector.session.connector
        assert tcp_connector.limit == 100  # default
        assert tcp_connector.limit_per_host == 30  # default


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])


"""
Unit tests for BybitRestClient.

Tests cover:
- HMAC signature generation (deterministic)
- Rate limiting (token bucket)
- Dry-run order placement
- Order cancellation
- Secret masking in logs
"""

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from tools.live.exchange import OrderStatus, PlaceOrderRequest, Side
from tools.live.exchange_bybit import BybitRestClient, RateLimiter
from tools.live.secrets import SecretProvider


class TestRateLimiter:
    """Test token bucket rate limiter."""

    def test_init(self):
        """Test rate limiter initialization."""
        clock = lambda: 1000.0
        limiter = RateLimiter(capacity=100, refill_rate=10.0, clock=clock)
        assert limiter._capacity == 100
        assert limiter._refill_rate == 10.0
        assert limiter._tokens == 100.0
        assert limiter._last_refill_time == 1000.0

    def test_acquire_success(self):
        """Test successful token acquisition."""
        clock_time = [1000.0]
        clock = lambda: clock_time[0]
        limiter = RateLimiter(capacity=100, refill_rate=10.0, clock=clock)
        
        assert limiter.acquire(10)
        assert limiter._tokens == 90.0

    def test_acquire_failure(self):
        """Test failed token acquisition when insufficient tokens."""
        clock_time = [1000.0]
        clock = lambda: clock_time[0]
        limiter = RateLimiter(capacity=100, refill_rate=10.0, clock=clock)
        
        # Consume all tokens
        assert limiter.acquire(100)
        assert limiter._tokens == 0.0
        
        # Should fail
        assert not limiter.acquire(1)

    def test_refill(self):
        """Test token refill over time."""
        clock_time = [1000.0]
        clock = lambda: clock_time[0]
        limiter = RateLimiter(capacity=100, refill_rate=10.0, clock=clock)
        
        # Consume tokens
        assert limiter.acquire(50)
        assert limiter._tokens == 50.0
        
        # Advance time by 5 seconds (should refill 50 tokens)
        clock_time[0] = 1005.0
        limiter._refill()
        assert limiter._tokens == 100.0  # Capped at capacity

    def test_refill_cap(self):
        """Test that tokens don't exceed capacity."""
        clock_time = [1000.0]
        clock = lambda: clock_time[0]
        limiter = RateLimiter(capacity=100, refill_rate=10.0, clock=clock)
        
        # Advance time by 20 seconds (should refill 200 tokens, but cap at 100)
        clock_time[0] = 1020.0
        limiter._refill()
        assert limiter._tokens == 100.0


class TestBybitRestClient:
    """Test Bybit REST client."""

    @pytest.fixture
    def mock_secret_provider(self):
        """Create mock secret provider."""
        provider = MagicMock(spec=SecretProvider)
        provider.get_api_key.return_value = "test_api_key_12345"
        provider.get_api_secret.return_value = "test_api_secret_67890"
        return provider

    @pytest.fixture
    def client(self, mock_secret_provider):
        """Create Bybit client for testing."""
        clock_time = [1000000]
        clock = lambda: clock_time[0]
        
        return BybitRestClient(
            secret_provider=mock_secret_provider,
            api_env="dev",
            network_enabled=False,
            clock=clock,
            fill_rate=1.0,  # Always fill
            seed=42,
        )

    def test_init(self, mock_secret_provider):
        """Test client initialization."""
        client = BybitRestClient(
            secret_provider=mock_secret_provider,
            api_env="dev",
            network_enabled=False,
        )
        
        assert client._api_env == "dev"
        assert client._network_enabled is False
        mock_secret_provider.get_api_key.assert_called_once_with("dev", "bybit")
        mock_secret_provider.get_api_secret.assert_called_once_with("dev", "bybit")

    def test_signature_generation(self, client):
        """Test HMAC signature generation (deterministic)."""
        timestamp = 1609459200000
        api_key = "test_api_key"
        recv_window = 5000
        query_string = "symbol=BTCUSDT&side=Buy"
        
        # Expected signature
        param_str = f"{timestamp}{api_key}{recv_window}{query_string}"
        expected_sig = hmac.new(
            b"test_api_secret_67890",
            param_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        
        # Generate signature
        sig = client._generate_signature(timestamp, api_key, recv_window, query_string)
        
        assert sig == expected_sig

    def test_build_headers(self, client):
        """Test HTTP header construction."""
        timestamp = 1609459200000
        signature = "test_signature_abc123"
        recv_window = 5000
        
        headers = client._build_headers(timestamp, signature, recv_window)
        
        assert headers["X-BAPI-API-KEY"] == "test_api_key_12345"
        assert headers["X-BAPI-SIGN"] == signature
        assert headers["X-BAPI-TIMESTAMP"] == "1609459200000"
        assert headers["X-BAPI-RECV-WINDOW"] == "5000"
        assert headers["Content-Type"] == "application/json"

    def test_place_limit_order_dryrun(self, client):
        """Test place limit order in dry-run mode."""
        request = PlaceOrderRequest(
            client_order_id="CLI00000001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            price=50000.0,
        )
        
        response = client.place_limit_order(request)
        
        assert response.success is True
        assert response.status == OrderStatus.OPEN
        assert response.order_id is not None
        assert "bybit_" in response.order_id
        assert "dry-run" in response.message.lower()

    def test_cancel_order_dryrun(self, client):
        """Test cancel order in dry-run mode."""
        # First place an order
        request = PlaceOrderRequest(
            client_order_id="CLI00000001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            price=50000.0,
        )
        place_resp = client.place_limit_order(request)
        
        # Get the client order ID from the created order
        orders = client.get_open_orders()
        client_order_id = orders[0].client_order_id
        
        # Then cancel it
        cancel_resp = client.cancel_order(client_order_id, "BTCUSDT")
        
        assert cancel_resp.success is True
        assert cancel_resp.status == OrderStatus.CANCELED

    def test_cancel_nonexistent_order(self, client):
        """Test canceling a non-existent order."""
        response = client.cancel_order("nonexistent_order", "BTCUSDT")
        
        assert response.success is False
        assert response.status == OrderStatus.REJECTED
        assert "not found" in response.message.lower()

    def test_get_open_orders(self, client):
        """Test getting open orders."""
        # Place two orders
        req1 = PlaceOrderRequest(
            client_order_id="CLI00000001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            price=50000.0,
        )
        client.place_limit_order(req1)
        
        req2 = PlaceOrderRequest(
            client_order_id="CLI00000002",
            symbol="ETHUSDT",
            side=Side.SELL,
            qty=1.0,
            price=3000.0,
        )
        client.place_limit_order(req2)
        
        # Get all open orders
        open_orders = client.get_open_orders()
        assert len(open_orders) == 2
        
        # Filter by symbol
        btc_orders = client.get_open_orders(symbol="BTCUSDT")
        assert len(btc_orders) == 1
        assert btc_orders[0].symbol == "BTCUSDT"

    def test_get_positions(self, client):
        """Test getting positions from filled orders."""
        # Place and fill an order (with fill_rate=1.0)
        request = PlaceOrderRequest(
            client_order_id="CLI00000001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            price=50000.0,
        )
        client.place_limit_order(request)
        
        # Process fills (advance clock past fill latency)
        clock_time = [1000000 + 150]  # Past fill latency
        client._clock = lambda: clock_time[0]
        
        fill_gen = client.stream_fills()
        fill = fill_gen()
        
        # Get positions
        positions = client.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "BTCUSDT"
        assert positions[0].qty == 0.1  # Positive means long

    def test_stream_fills(self, client):
        """Test fill event generation."""
        # Place order
        request = PlaceOrderRequest(
            client_order_id="CLI00000001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            price=50000.0,
        )
        client.place_limit_order(request)
        
        # Advance clock past fill latency
        clock_time = [1000000 + 150]
        client._clock = lambda: clock_time[0]
        
        # Get fill generator
        fill_gen = client.stream_fills()
        fill = fill_gen()
        
        assert fill is not None
        assert fill.symbol == "BTCUSDT"
        assert fill.side == Side.BUY
        assert fill.qty == 0.1
        assert fill.price == 50000.0

    def test_stream_fills_no_fills(self, client):
        """Test stream_fills when no fills are ready."""
        # Don't advance clock
        fill_gen = client.stream_fills()
        fill = fill_gen()
        
        assert fill is None

    def test_rate_limit_exceeded(self, client):
        """Test rate limit enforcement."""
        # Exhaust rate limiter
        for _ in range(100):
            client._rate_limiter.acquire(1)
        
        # Should return error response
        response = client._http_post("/test/endpoint", {"test": "param"})
        assert response["retCode"] == 10006
        assert "rate limit" in response["retMsg"].lower()

    def test_network_enabled_raises(self, mock_secret_provider):
        """Test that network-enabled mode raises NotImplementedError."""
        client = BybitRestClient(
            secret_provider=mock_secret_provider,
            api_env="dev",
            network_enabled=True,
        )
        
        with pytest.raises(NotImplementedError, match="Network-enabled mode not implemented"):
            client._http_post("/test/endpoint", {"test": "param"})

    def test_secret_masking(self, mock_secret_provider):
        """Test that secrets are masked in logs."""
        with patch("tools.live.exchange_bybit.logging.getLogger") as mock_logger:
            mock_log = MagicMock()
            mock_logger.return_value = mock_log
            
            client = BybitRestClient(
                secret_provider=mock_secret_provider,
                api_env="dev",
                network_enabled=False,
            )
            
            # Check that init log doesn't contain full API key
            assert mock_log.info.called
            call_args = str(mock_log.info.call_args)
            assert "test_api_key_12345" not in call_args or "***" in call_args

    def test_deterministic_fill_scheduling(self, mock_secret_provider):
        """Test that fill scheduling is deterministic with same seed."""
        clock_time = [1000000]
        clock = lambda: clock_time[0]
        
        # Create two clients with same seed
        client1 = BybitRestClient(
            secret_provider=mock_secret_provider,
            api_env="dev",
            network_enabled=False,
            clock=clock,
            fill_rate=0.5,
            seed=42,
        )
        
        client2 = BybitRestClient(
            secret_provider=mock_secret_provider,
            api_env="dev",
            network_enabled=False,
            clock=clock,
            fill_rate=0.5,
            seed=42,
        )
        
        # Place same orders
        req = PlaceOrderRequest(
            client_order_id="CLI00000001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            price=50000.0,
        )
        
        resp1 = client1.place_limit_order(req)
        resp2 = client2.place_limit_order(req)
        
        # Should have same number of scheduled fills
        assert len(client1._scheduled_fills) == len(client2._scheduled_fills)

    def test_fill_rate_zero(self, mock_secret_provider):
        """Test that no fills are scheduled when fill_rate=0."""
        clock_time = [1000000]
        clock = lambda: clock_time[0]
        
        client = BybitRestClient(
            secret_provider=mock_secret_provider,
            api_env="dev",
            network_enabled=False,
            clock=clock,
            fill_rate=0.0,
            seed=42,
        )
        
        request = PlaceOrderRequest(
            client_order_id="CLI00000001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            price=50000.0,
        )
        client.place_limit_order(request)
        
        # No fills should be scheduled
        assert len(client._scheduled_fills) == 0

    def test_get_current_time_ms(self, client):
        """Test get_current_time_ms returns clock value."""
        assert client.get_current_time_ms() == 1000000


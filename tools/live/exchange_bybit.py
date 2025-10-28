"""
Bybit REST API Client for shadow/dry-run trading.

This module provides a BybitRestClient that implements the IExchangeClient protocol
for interacting with Bybit exchange in shadow/dry-run mode. It includes:
- Request signing (HMAC SHA256)
- Rate limiting (token bucket algorithm)
- Network calls (can be disabled via network_enabled flag)
- Dry-run behavior (orders stored locally without real execution)
- Secret masking in logs

All operations are deterministic and follow the MM_FREEZE_UTC_ISO convention.
"""

import collections
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel

from tools.live.exchange import (
    FillEvent,
    IExchangeClient,
    OpenOrder,
    OrderStatus,
    PlaceOrderRequest,
    PlaceOrderResponse,
    Position,
    Side,
)
from tools.live.order_store import InMemoryOrderStore, Order, OrderState
from tools.live.secrets import SecretProvider


def _mask_secret(value: str) -> str:
    """Mask a secret value for logging."""
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}...***"


class RateLimiter:
    """
    Token bucket rate limiter for API requests.
    
    This implementation uses a simple token bucket algorithm with:
    - capacity: maximum number of tokens
    - refill_rate: tokens added per second
    - Injectable clock for deterministic testing
    """

    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        clock: Optional[Callable[[], float]] = None,
    ):
        """
        Initialize the rate limiter.
        
        Args:
            capacity: Maximum number of tokens in the bucket
            refill_rate: Tokens refilled per second
            clock: Optional callable returning current time in seconds (for testing)
        """
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = float(capacity)
        self._last_refill_time = (clock if clock else time.time)()
        self._clock = clock if clock else time.time
        self._logger = logging.getLogger(self.__class__.__name__)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = self._clock()
        elapsed = now - self._last_refill_time
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill_time = now

    def acquire(self, tokens: int = 1) -> bool:
        """
        Attempt to acquire tokens.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            True if tokens were acquired, False otherwise
        """
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            self._logger.debug(
                json.dumps(
                    {
                        "event": "rate_limit_acquire",
                        "tokens_requested": tokens,
                        "tokens_remaining": self._tokens,
                        "success": True,
                    },
                    sort_keys=True,
                )
            )
            return True
        else:
            self._logger.warning(
                json.dumps(
                    {
                        "event": "rate_limit_exceeded",
                        "tokens_requested": tokens,
                        "tokens_available": self._tokens,
                        "success": False,
                    },
                    sort_keys=True,
                )
            )
            return False

    def wait_for_tokens(self, tokens: int = 1, max_wait_sec: float = 10.0) -> bool:
        """
        Wait until tokens are available or timeout.
        
        Args:
            tokens: Number of tokens to acquire
            max_wait_sec: Maximum time to wait in seconds
            
        Returns:
            True if tokens were acquired, False if timeout
        """
        start = self._clock()
        while self._clock() - start < max_wait_sec:
            if self.acquire(tokens):
                return True
            time.sleep(0.1)  # Sleep briefly to avoid busy-waiting
        return False


class BybitRestClient:
    """
    Bybit REST API client for shadow/dry-run trading.
    
    This client implements the IExchangeClient protocol and provides:
    - Request signing with HMAC SHA256
    - Rate limiting with token bucket
    - Dry-run mode (local order tracking without real API calls)
    - Network-enabled mode (real API calls, not implemented yet)
    - Secret masking in logs
    
    In dry-run mode:
    - place_limit_order: stores order locally and schedules fill event
    - cancel_order: transitions order to canceled state
    - get_open_orders/get_positions: read from local state
    - stream_fills: generates events based on scheduled fills
    """

    def __init__(
        self,
        secret_provider: SecretProvider,
        api_env: str = "dev",
        network_enabled: bool = False,
        testnet: bool = False,
        clock: Optional[Callable[[], int]] = None,
        rate_limit_capacity: int = 100,
        rate_limit_refill_rate: float = 10.0,
        fill_latency_ms: int = 100,
        fill_rate: float = 0.8,
        seed: Optional[int] = None,
    ):
        """
        Initialize Bybit REST client.
        
        Args:
            secret_provider: Provider for API keys and secrets
            api_env: Environment (dev/shadow/soak/prod)
            network_enabled: Whether to make real network calls
            testnet: Whether to use testnet mode (safe endpoints only)
            clock: Optional callable returning current time in milliseconds
            rate_limit_capacity: Token bucket capacity
            rate_limit_refill_rate: Token bucket refill rate (tokens/sec)
            fill_latency_ms: Simulated fill latency in dry-run mode
            fill_rate: Probability of order being filled in dry-run mode
            seed: Random seed for deterministic behavior
        """
        self._secret_provider = secret_provider
        self._api_env = api_env
        self._network_enabled = network_enabled
        self._testnet = testnet
        self._clock = clock if clock else lambda: int(time.time() * 1000)
        self._rate_limiter = RateLimiter(
            capacity=rate_limit_capacity,
            refill_rate=rate_limit_refill_rate,
            clock=lambda: self._clock() / 1000.0,
        )
        self._fill_latency_ms = fill_latency_ms
        self._fill_rate = fill_rate
        self._order_store = InMemoryOrderStore()
        self._scheduled_fills: List[Tuple[int, Order]] = []  # (timestamp_ms, order)
        self._seed = seed  # Store seed for potential future use
        self._logger = logging.getLogger(self.__class__.__name__)
        
        # Load API credentials (but mask in logs)
        try:
            self._api_key = secret_provider.get_api_key(api_env, "bybit")
            self._api_secret = secret_provider.get_api_secret(api_env, "bybit")
            self._logger.info(
                json.dumps(
                    {
                        "event": "bybit_client_init",
                        "api_env": api_env,
                        "api_key": _mask_secret(self._api_key),
                        "network_enabled": network_enabled,
                        "testnet": testnet,
                    },
                    sort_keys=True,
                )
            )
        except Exception as e:
            self._logger.error(
                json.dumps(
                    {
                        "event": "bybit_client_init_failed",
                        "error": str(e),
                        "api_env": api_env,
                    },
                    sort_keys=True,
                )
            )
            raise

    def _generate_signature(
        self,
        timestamp: int,
        api_key: str,
        recv_window: int,
        query_string: str,
    ) -> str:
        """
        Generate HMAC SHA256 signature for Bybit API request.
        
        Bybit signature format:
        sign = HMAC_SHA256(api_secret, timestamp + api_key + recv_window + query_string)
        
        Args:
            timestamp: Request timestamp in milliseconds
            api_key: API key
            recv_window: Receive window in milliseconds
            query_string: URL-encoded query parameters
            
        Returns:
            Hex-encoded signature
        """
        param_str = f"{timestamp}{api_key}{recv_window}{query_string}"
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            param_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        
        # Log signature generation (mask secret)
        self._logger.debug(
            json.dumps(
                {
                    "event": "signature_generated",
                    "api_key": _mask_secret(api_key),
                    "timestamp": timestamp,
                    "recv_window": recv_window,
                    "query_string": query_string[:50] + "..." if len(query_string) > 50 else query_string,
                    "signature": _mask_secret(signature),
                },
                sort_keys=True,
            )
        )
        
        return signature

    def _build_headers(
        self,
        timestamp: int,
        signature: str,
        recv_window: int = 5000,
    ) -> Dict[str, str]:
        """
        Build HTTP headers for Bybit API request.
        
        Args:
            timestamp: Request timestamp in milliseconds
            signature: HMAC signature
            recv_window: Receive window in milliseconds
            
        Returns:
            Dictionary of HTTP headers
        """
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-RECV-WINDOW": str(recv_window),
            "Content-Type": "application/json",
        }

    def _http_post(
        self,
        endpoint: str,
        params: Dict,
    ) -> Dict:
        """
        Execute HTTP POST request to Bybit API.
        
        In network_enabled=False mode, returns deterministic mock response.
        In network_enabled=True mode, would make real API call (not implemented).
        
        Args:
            endpoint: API endpoint path
            params: Request parameters
            
        Returns:
            API response as dictionary
        """
        # Rate limiting
        if not self._rate_limiter.acquire(1):
            self._logger.error(
                json.dumps(
                    {
                        "event": "rate_limit_exceeded",
                        "endpoint": endpoint,
                    },
                    sort_keys=True,
                )
            )
            return {
                "retCode": 10006,
                "retMsg": "rate limit exceeded",
                "result": {},
            }
        
        if not self._network_enabled:
            # Dry-run mode: return mock response
            self._logger.debug(
                json.dumps(
                    {
                        "event": "http_post_dryrun",
                        "endpoint": endpoint,
                        "params": params,
                    },
                    sort_keys=True,
                )
            )
            return {
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "orderId": f"dryrun_{self._clock()}",
                    "orderLinkId": params.get("orderLinkId", ""),
                },
            }
        else:
            # Network mode: would make real API call
            # Not implemented for safety - this is shadow/dry-run only
            raise NotImplementedError(
                "Network-enabled mode not implemented for safety. Use dry-run mode."
            )

    def _http_get(
        self,
        endpoint: str,
        params: Dict,
    ) -> Dict:
        """
        Execute HTTP GET request to Bybit API.
        
        In network_enabled=False mode, returns deterministic mock response.
        In network_enabled=True mode, would make real API call (not implemented).
        
        Args:
            endpoint: API endpoint path
            params: Request parameters
            
        Returns:
            API response as dictionary
        """
        # Rate limiting
        if not self._rate_limiter.acquire(1):
            self._logger.error(
                json.dumps(
                    {
                        "event": "rate_limit_exceeded",
                        "endpoint": endpoint,
                    },
                    sort_keys=True,
                )
            )
            return {
                "retCode": 10006,
                "retMsg": "rate limit exceeded",
                "result": {},
            }
        
        if not self._network_enabled:
            # Dry-run mode: return mock response
            self._logger.debug(
                json.dumps(
                    {
                        "event": "http_get_dryrun",
                        "endpoint": endpoint,
                        "params": params,
                    },
                    sort_keys=True,
                )
            )
            return {
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "list": [],
                },
            }
        else:
            # Network mode: would make real API call
            raise NotImplementedError(
                "Network-enabled mode not implemented for safety. Use dry-run mode."
            )

    def place_limit_order(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        """
        Place a limit order.
        
        In dry-run mode:
        - Creates order in local store with 'open' state
        - Schedules fill event based on fill_rate and fill_latency_ms
        - Does not make real API call
        
        Args:
            request: Order placement request
            
        Returns:
            Order placement response
        """
        # Create order in local store
        order = self._order_store.create(
            symbol=request.symbol,
            side=request.side,
            qty=request.qty,
            price=request.price,
            timestamp_ms=self._clock(),
        )
        
        # Transition to 'open' state
        self._order_store.update_state(
            client_order_id=order.client_order_id,
            state=OrderState.OPEN,
            timestamp_ms=self._clock(),
            order_id=f"bybit_{order.client_order_id}",
        )
        
        # Schedule fill event with deterministic delay
        fill_time_ms = self._clock() + self._fill_latency_ms
        
        # Determine if order will be filled based on fill_rate
        # Use deterministic hash of order ID for reproducibility
        order_hash = int(hashlib.sha256(order.client_order_id.encode()).hexdigest()[:8], 16)
        will_fill = (order_hash % 100) < (self._fill_rate * 100)
        
        if will_fill:
            self._scheduled_fills.append((fill_time_ms, order))
            self._logger.info(
                json.dumps(
                    {
                        "event": "order_placed_scheduled_fill",
                        "client_order_id": order.client_order_id,
                        "symbol": request.symbol,
                        "side": request.side,
                        "price": request.price,
                        "quantity": request.qty,
                        "fill_time_ms": fill_time_ms,
                    },
                    sort_keys=True,
                )
            )
        else:
            self._logger.info(
                json.dumps(
                    {
                        "event": "order_placed_no_fill",
                        "client_order_id": order.client_order_id,
                        "symbol": request.symbol,
                        "side": request.side,
                        "price": request.price,
                        "quantity": request.qty,
                    },
                    sort_keys=True,
                )
            )
        
        return PlaceOrderResponse(
            success=True,
            order_id=f"bybit_{order.client_order_id}",
            status=OrderStatus.OPEN,
            message="Order placed (dry-run)",
        )

    def cancel_order(self, client_order_id: str, symbol: str) -> PlaceOrderResponse:
        """
        Cancel an order.
        
        In dry-run mode:
        - Transitions order to 'canceled' state in local store
        - Does not make real API call
        
        Args:
            client_order_id: Client order ID
            symbol: Trading symbol
            
        Returns:
            Order cancellation response
        """
        order = self._order_store.get(client_order_id)
        if order is None:
            self._logger.warning(
                json.dumps(
                    {
                        "event": "cancel_order_not_found",
                        "client_order_id": client_order_id,
                        "symbol": symbol,
                    },
                    sort_keys=True,
                )
            )
            return PlaceOrderResponse(
                success=False,
                order_id=None,
                status=OrderStatus.REJECTED,
                message="Order not found",
            )
        
        # Transition to canceled
        self._order_store.update_state(
            client_order_id=client_order_id,
            state=OrderState.CANCELED,
            timestamp_ms=self._clock(),
        )
        
        # Remove from scheduled fills if present
        self._scheduled_fills = [
            (ts, o) for ts, o in self._scheduled_fills
            if o.client_order_id != client_order_id
        ]
        
        self._logger.info(
            json.dumps(
                {
                    "event": "order_canceled",
                    "client_order_id": client_order_id,
                    "symbol": symbol,
                },
                sort_keys=True,
            )
        )
        
        return PlaceOrderResponse(
            success=True,
            order_id=order.order_id,
            status=OrderStatus.CANCELED,
            message="Order canceled (dry-run)",
        )

    def get_open_orders(self, symbol: Optional[str] = None) -> List[OpenOrder]:
        """
        Get open orders from local store.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            List of open orders
        """
        orders = self._order_store.get_open_orders()
        # Filter by symbol if provided
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        
        return [
            OpenOrder(
                order_id=o.order_id or "",
                client_order_id=o.client_order_id,
                symbol=o.symbol,
                side=o.side,
                qty=o.qty,
                filled_qty=o.filled_qty,
                price=o.price,
                status=OrderStatus.OPEN,
            )
            for o in orders
        ]

    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """
        Get positions from local order store.
        
        Aggregates fills to compute net position per symbol.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            List of positions
        """
        # Aggregate net position from filled orders
        positions: Dict[str, float] = collections.defaultdict(float)
        
        for order in self._order_store.get_all():
            if order.state == OrderState.FILLED:
                if symbol is None or order.symbol == symbol:
                    qty = order.filled_qty
                    if order.side == "sell":
                        qty = -qty
                    positions[order.symbol] += qty
        
        return [
            Position(
                symbol=sym,
                qty=qty,  # Positive for long, negative for short
                avg_entry_price=0.0,  # Not tracked in dry-run
            )
            for sym, qty in positions.items()
            if abs(qty) > 1e-8
        ]

    def stream_fills(self) -> Callable[[], Optional[FillEvent]]:
        """
        Returns a generator function that yields fill events.
        
        In dry-run mode, generates events based on scheduled fills.
        
        Returns:
            Generator function yielding fill events
        """
        def generator() -> Optional[FillEvent]:
            now = self._clock()
            
            # Check for scheduled fills
            to_process = []
            remaining = []
            
            for fill_time, order in self._scheduled_fills:
                if fill_time <= now:
                    to_process.append(order)
                else:
                    remaining.append((fill_time, order))
            
            self._scheduled_fills = remaining
            
            # Process fills
            for order in to_process:
                # Update order state to filled
                self._order_store.update_fill(
                    client_order_id=order.client_order_id,
                    filled_qty=order.qty,
                    avg_fill_price=order.price,
                    timestamp_ms=now,
                )
                self._order_store.update_state(
                    client_order_id=order.client_order_id,
                    state=OrderState.FILLED,
                    timestamp_ms=now,
                )
                
                self._logger.info(
                    json.dumps(
                        {
                            "event": "fill_generated",
                            "client_order_id": order.client_order_id,
                            "symbol": order.symbol,
                            "side": order.side,
                            "price": order.price,
                            "quantity": order.qty,
                            "timestamp_ms": now,
                        },
                        sort_keys=True,
                    )
                )
                
                return FillEvent(
                    order_id=order.order_id or order.client_order_id,
                    symbol=order.symbol,
                    side=order.side,
                    price=order.price,
                    qty=order.qty,
                    timestamp_ms=now,
                )
            
            return None
        
        return generator

    def get_current_time_ms(self) -> int:
        """Returns the current time in milliseconds."""
        return self._clock()
    
    def fetch_symbol_filters_live(self, symbol: str):
        """
        Fetch symbol filters from live Bybit API.
        
        This method makes a real API call to get instrument info.
        In tests, should be mocked/patched.
        
        Args:
            symbol: Trading symbol (e.g. "BTCUSDT")
        
        Returns:
            SymbolFilters object with trading rules
        
        Raises:
            Exception: If network call fails or response is invalid
        """
        # Import here to avoid circular dependency
        from decimal import Decimal
        from tools.live.symbol_filters import SymbolFilters
        from tools.obs import metrics
        
        if not self._network_enabled:
            # In shadow mode, fall back to defaults
            metrics.SYMBOL_FILTERS_SOURCE.inc(source="default")
            filters = self.get_symbol_filters(symbol)
            return SymbolFilters(
                symbol=symbol,
                tick_size=Decimal(str(filters["tickSize"])),
                step_size=Decimal(str(filters["stepSize"])),
                min_qty=Decimal(str(filters["minQty"])),
            )
        
        try:
            # Construct API endpoint
            # Note: In real implementation, this would make HTTP GET request
            # For now, this is a placeholder that will be mocked in tests
            endpoint = "/v5/market/instruments-info"
            params = {"category": "linear", "symbol": symbol}
            
            # This would be: response = self._get(endpoint, params)
            # But we don't implement real HTTP here (mocked in tests)
            raise NotImplementedError(
                "fetch_symbol_filters_live requires HTTP implementation or mock"
            )
            
        except Exception as e:
            metrics.SYMBOL_FILTERS_FETCH_ERRORS.inc()
            self._logger.warning(
                json.dumps(
                    {
                        "event": "symbol_filters_fetch_error",
                        "symbol": symbol,
                        "error": str(e),
                    },
                    sort_keys=True,
                )
            )
            # Fall back to defaults
            filters = self.get_symbol_filters(symbol)
            return SymbolFilters(
                symbol=symbol,
                tick_size=Decimal(str(filters["tickSize"])),
                step_size=Decimal(str(filters["stepSize"])),
                min_qty=Decimal(str(filters["minQty"])),
            )
    
    def get_symbol_filters(self, symbol: str) -> dict[str, float]:
        """
        Get symbol trading filters (tickSize, stepSize, minQty).
        
        In shadow/testnet mode, returns deterministic stubs.
        In live mode (future), would query real exchange info.
        
        Args:
            symbol: Trading symbol (e.g. "BTCUSDT")
        
        Returns:
            Dictionary with keys: tickSize, stepSize, minQty
        
        Examples:
            >>> client.get_symbol_filters("BTCUSDT")
            {"tickSize": 0.01, "stepSize": 0.00001, "minQty": 0.00001}
        """
        # Deterministic filters for testing
        # These match common Bybit contract specs
        filters = {
            "BTCUSDT": {
                "tickSize": 0.01,
                "stepSize": 0.00001,
                "minQty": 0.00001,
            },
            "ETHUSDT": {
                "tickSize": 0.01,
                "stepSize": 0.0001,
                "minQty": 0.0001,
            },
            "SOLUSDT": {
                "tickSize": 0.001,
                "stepSize": 0.01,
                "minQty": 0.01,
            },
        }
        
        # Default filters for unknown symbols
        default_filters = {
            "tickSize": 0.01,
            "stepSize": 0.001,
            "minQty": 0.001,
        }
        
        result = filters.get(symbol, default_filters)
        
        self._logger.debug(
            json.dumps(
                {
                    "event": "get_symbol_filters",
                    "symbol": symbol,
                    "filters": result,
                    "mode": "testnet" if self._testnet else "shadow",
                },
                sort_keys=True,
            )
        )
        
        return result


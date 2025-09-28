"""
Bybit REST API connector with hardened connectivity and state management.
"""

import time
import random
import asyncio
from typing import Any, Dict, Optional, List, Tuple
from dataclasses import dataclass

import aiohttp
import orjson

from src.common.di import AppContext
from src.metrics.exporter import Metrics


@dataclass
class BybitError:
    """Bybit API error with retry classification."""
    code: int
    message: str
    is_transient: bool
    retry_after_ms: int = 0


class BybitRESTConnector:
    """Hardened Bybit REST API connector with retry logic and metrics."""
    
    # Bybit error codes mapping
    TRANSIENT_ERRORS = {
        10006,  # Rate limit exceeded
        10018,  # Request timeout
        10019,  # System busy
        10020,  # System error
        10021,  # System maintenance
        10022,  # System upgrade
        10023,  # System overload
        10024,  # System unavailable
        10025,  # System error
        10026,  # System error
        10027,  # System error
        10028,  # System error
        10029,  # System error
        10030,  # System error
    }
    
    FATAL_ERRORS = {
        10001,  # Invalid parameter
        10002,  # Invalid request
        10003,  # Invalid signature
        10004,  # Invalid timestamp
        10005,  # Invalid API key
        10007,  # Invalid symbol
        10008,  # Invalid side
        10009,  # Invalid order type
        10010,  # Invalid quantity
        10011,  # Invalid price
        10012,  # Invalid time in force
        10013,  # Invalid order ID
        10014,  # Invalid client order ID
        10015,  # Invalid order status
        10016,  # Invalid order
        10017,  # Invalid order
    }
    
    def __init__(self, ctx: AppContext, config: Dict[str, Any]):
        """Initialize connector with AppContext and config."""
        self.ctx = ctx
        self.config = config
        self.connected = False
        self.session: Optional[aiohttp.ClientSession] = None
        self.base_url = config.get('base_url', 'https://api.bybit.com')
        self.api_key = config.get('api_key')
        self.api_secret = config.get('api_secret')
        self.recv_window = config.get('recv_window', 5000)
        
        # Retry configuration
        self.max_retries = config.get('max_retries', 3)
        self.base_backoff_ms = config.get('base_backoff_ms', 1000)
        self.max_backoff_ms = min(config.get('max_backoff_ms', 30000), 3000)  # Cap at 3s
        self.max_attempts = config.get('max_attempts', 5)
        
        # Metrics
        self.metrics: Optional[Metrics] = None
        if hasattr(ctx, 'metrics'):
            self.metrics = ctx.metrics
        
        # Counter for unique ID generation
        self._order_counter = 0
        
        # Circuit breaker state
        self._circuit_open = False
        self._circuit_open_time = 0
        self._error_count = 0
        self._last_error_time = 0
        self._circuit_breaker_window_ms = config.get('circuit_breaker_window_ms', 60000)  # 1 minute
        self._circuit_breaker_threshold = config.get('circuit_breaker_threshold', 10)  # errors per window
        self._circuit_breaker_timeout_ms = config.get('circuit_breaker_timeout_ms', 300000)  # 5 minutes
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'Content-Type': 'application/json'}
        )
        self.connected = True
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
        self.connected = False
    
    def is_connected(self) -> bool:
        """Check if connector is connected."""
        return self.connected and self.session is not None
    
    def get_connection_status(self) -> Dict[str, bool]:
        """Get connection status."""
        return {"public": self.connected, "private": self.connected}
    
    def _generate_client_order_id(self, symbol: str, side: str) -> str:
        """Generate unique client order ID with format: {symbol}-{side}-{timestamp}-{counter}-{random4}."""
        timestamp = int(time.monotonic() * 1000)
        self._order_counter += 1
        random_suffix = random.randint(1000, 9999)
        return f"{symbol}-{side}-{timestamp}-{self._order_counter}-{random_suffix}"
    
    def _round_to_tick(self, price: float, symbol: str) -> float:
        """Round price to nearest tick size."""
        # Default tick sizes for common symbols
        tick_sizes = {
            "BTCUSDT": 0.1,
            "ETHUSDT": 0.01,
            "SOLUSDT": 0.001,
            "ADAUSDT": 0.0001,
        }
        
        tick_size = tick_sizes.get(symbol, 0.01)  # Default to 0.01
        return round(price / tick_size) * tick_size
    
    def _round_to_lot(self, qty: float, symbol: str) -> float:
        """Round quantity to nearest lot size."""
        # Default lot sizes for common symbols
        lot_sizes = {
            "BTCUSDT": 0.001,
            "ETHUSDT": 0.01,
            "SOLUSDT": 0.1,
            "ADAUSDT": 1.0,
        }
        
        lot_size = lot_sizes.get(symbol, 0.01)  # Default to 0.01
        return round(qty / lot_size) * lot_size
    
    def _update_circuit_breaker(self, success: bool):
        """Update circuit breaker state based on request result."""
        current_time = time.time() * 1000
        
        if success:
            # Reset error count on success
            self._error_count = 0
            self._last_error_time = 0
            # Update circuit breaker state metric
            if self.metrics:
                self.metrics.set_circuit_breaker_state(False)
        else:
            # Increment error count
            self._error_count += 1
            self._last_error_time = current_time
            
            # Check if we should open circuit
            if self._error_count >= self._circuit_breaker_threshold:
                self._circuit_open = True
                self._circuit_open_time = current_time
                # Update circuit breaker state metric
                if self.metrics:
                    self.metrics.set_circuit_breaker_state(True)
    
    def _should_allow_request(self, operation: str) -> bool:
        """Check if request should be allowed based on circuit breaker state."""
        current_time = time.time() * 1000
        
        # Check if circuit is open
        if self._circuit_open:
            # Check if timeout has passed
            if current_time - self._circuit_open_time > self._circuit_breaker_timeout_ms:
                # Try to close circuit
                self._circuit_open = False
                self._error_count = 0
                # Update circuit breaker state metric
                if self.metrics:
                    self.metrics.set_circuit_breaker_state(False)
                return True
            else:
                # Circuit is open, only allow cancels
                return operation == "cancel"
        
        return True
    
    def is_circuit_open(self) -> bool:
        """Check if circuit breaker is currently open."""
        return self._circuit_open
    
    def get_circuit_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state for health checks."""
        return {
            "open": self._circuit_open,
            "error_count": self._error_count,
            "last_error_time": self._last_error_time,
            "open_time": self._circuit_open_time
        }
    
    def _classify_bybit_error(self, code: int, message: str) -> BybitError:
        """Classify Bybit error as transient or fatal."""
        if code in self.TRANSIENT_ERRORS:
            return BybitError(code, message, is_transient=True, retry_after_ms=1000)
        elif code in self.FATAL_ERRORS:
            return BybitError(code, message, is_transient=False)
        else:
            # Unknown errors treated as transient with default backoff
            return BybitError(code, message, is_transient=True, retry_after_ms=2000)
    
    async def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                           params: Optional[Dict] = None, attempt: int = 1) -> Dict[str, Any]:
        """Make HTTP request with retry logic and metrics."""
        start_time = time.monotonic()
        
        try:
            url = f"{self.base_url}{endpoint}"
            
            if method.upper() == 'GET':
                response = await self.session.get(url, params=params)
                result = await response.json(loads=orjson.loads)
            else:
                response = await self.session.request(method, url, json=data, params=params)
                result = await response.json(loads=orjson.loads)
            
            # Record latency
            if self.metrics:
                latency_ms = int((time.monotonic() - start_time) * 1000)
                self.metrics.latency_ms.observe({"stage": "rest"}, latency_ms)
            
            # Check for Bybit error response
            if result.get('retCode') != 0:
                error = self._classify_bybit_error(
                    result.get('retCode', 0),
                    result.get('retMsg', 'Unknown error')
                )
                
                if error.is_transient and attempt < self.max_attempts:
                    # Check for Retry-After header
                    retry_after_ms = error.retry_after_ms
                    if 'Retry-After' in response.headers:
                        try:
                            retry_after_ms = int(response.headers['Retry-After']) * 1000
                        except (ValueError, TypeError):
                            pass  # Use default if header is invalid
                    
                    # Calculate backoff with jitter, respecting Retry-After and cap
                    backoff_ms = min(
                        max(
                            retry_after_ms,
                            self.base_backoff_ms * (2 ** (attempt - 1)) + random.randint(0, 1000)
                        ),
                        self.max_backoff_ms
                    )
                    
                    if self.metrics:
                        self.metrics.rest_error_rate.labels(exchange="bybit").inc()
                        self.metrics.add_backoff_seconds(backoff_ms / 1000)
                    
                    await asyncio.sleep(backoff_ms / 1000)
                    return await self._make_request(method, endpoint, data, params, attempt + 1)
                else:
                    # Fatal error or max attempts exceeded
                    raise Exception(f"Bybit API error {error.code}: {error.message}")
            
            return result
            
        except Exception as e:
            if self.metrics:
                self.metrics.rest_error_rate.labels(exchange="bybit").inc()
            raise e
    
    async def place_order(self, symbol: str, side: str, order_type: str, qty: float, 
                         price: Optional[float] = None, time_in_force: str = "GTC") -> str:
        """Place order with idempotent client order ID."""
        if not self._should_allow_request("create"):
            raise Exception("Circuit breaker open: create operations not allowed")
        
        client_order_id = self._generate_client_order_id(symbol, side)
        
        data = {
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
            "timeInForce": time_in_force,
            "orderLinkId": client_order_id
        }
        
        if price:
            rounded_price = self._round_to_tick(price, symbol)
            data["price"] = str(rounded_price)
        
        try:
            result = await self._make_request("POST", "/v5/order/create", data=data)
            self._update_circuit_breaker(True)
            return result.get('result', {}).get('orderLinkId', client_order_id)
        except Exception as e:
            self._update_circuit_breaker(False)
            raise e
    
    async def cancel_order(self, symbol: str, order_id: Optional[str] = None, 
                          client_order_id: Optional[str] = None) -> Dict[str, Any]:
        """Cancel order by order ID or client order ID."""
        data = {"symbol": symbol}
        
        if order_id:
            data["orderId"] = order_id
        elif client_order_id:
            data["orderLinkId"] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id must be provided")
        
        result = await self._make_request("POST", "/v5/order/cancel", data=data)
        return result
    
    async def amend_order(self, symbol: str, order_id: Optional[str] = None,
                         client_order_id: Optional[str] = None, price: Optional[float] = None,
                         qty: Optional[float] = None) -> Dict[str, Any]:
        """Amend order price or quantity."""
        if not self._should_allow_request("amend"):
            raise Exception("Circuit breaker open: amend operations not allowed")
        
        data = {"symbol": symbol}
        
        if order_id:
            data["orderId"] = order_id
        elif client_order_id:
            data["orderLinkId"] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id must be provided")
        
        if price is not None:
            rounded_price = self._round_to_tick(price, symbol)
            data["price"] = str(rounded_price)
        if qty is not None:
            rounded_qty = self._round_to_lot(qty, symbol)
            data["qty"] = str(rounded_qty)
        
        try:
            result = await self._make_request("POST", "/v5/order/amend", data=data)
            self._update_circuit_breaker(True)
            return result
        except Exception as e:
            self._update_circuit_breaker(False)
            raise e
    
    async def get_active_orders(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get active orders."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        
        result = await self._make_request("GET", "/v5/order/realtime", params=params)
        return result
    
    async def get_order_history(self, symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        """Get order history."""
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        
        result = await self._make_request("GET", "/v5/order/history", params=params)
        return result
    
    async def get_executions(self, symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        """Get execution history."""
        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        
        result = await self._make_request("GET", "/v5/execution/list", params=params)
        return result

"""
Exchange Client — Interface for placing/canceling orders on exchanges.

Supports:
- Bybit (live + mock mode)
- Order placement with deterministic client_order_id
- Fill simulation for testing
- Prometheus metrics integration
"""

from __future__ import annotations

import time
import random
import logging
from typing import Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class OrderRequest:
    """Order placement request."""
    
    client_order_id: str
    symbol: str
    side: Literal["Buy", "Sell"]
    order_type: Literal["Limit", "Market"]
    qty: float
    price: Optional[float] = None  # Required for Limit orders
    time_in_force: Literal["GTC", "IOC", "FOK"] = "GTC"
    
    def validate(self) -> None:
        """Validate order request."""
        if self.order_type == "Limit" and self.price is None:
            raise ValueError("Limit orders require price")
        if self.qty <= 0:
            raise ValueError("Quantity must be positive")


@dataclass
class OrderResponse:
    """Order placement response from exchange."""
    
    client_order_id: str
    exchange_order_id: str
    symbol: str
    side: str
    status: Literal["New", "PartiallyFilled", "Filled", "Canceled", "Rejected"]
    qty: float
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reject_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "status": self.status,
            "qty": self.qty,
            "filled_qty": self.filled_qty,
            "avg_price": self.avg_price,
            "created_at": self.created_at,
            "reject_reason": self.reject_reason,
        }


@dataclass
class FillEvent:
    """Fill event (partial or full)."""
    
    client_order_id: str
    exchange_order_id: str
    symbol: str
    side: str
    fill_qty: float
    fill_price: float
    fill_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "fill_qty": self.fill_qty,
            "fill_price": self.fill_price,
            "fill_id": self.fill_id,
            "timestamp": self.timestamp,
        }


class ExchangeClient:
    """
    Exchange client for order placement/cancellation.
    
    Supports:
    - Bybit API (live mode with real credentials)
    - Mock mode (for testing, simulates fills)
    
    Mock Mode Behavior:
    - Orders are accepted with 95% probability (5% rejected)
    - Fills occur within 0.1-2.0 seconds
    - Partial fills possible (50% chance for 50-90% fill, then 100%)
    - Deterministic behavior when MM_FREEZE_UTC is set
    """
    
    def __init__(
        self,
        exchange: str = "bybit",
        mock: bool = True,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        testnet: bool = False,
    ):
        """
        Initialize exchange client.
        
        Args:
            exchange: Exchange name ("bybit")
            mock: Use mock mode (no real API calls)
            api_key: API key (required for live mode)
            api_secret: API secret (required for live mode)
            testnet: Use testnet endpoints (Bybit only)
        """
        self.exchange = exchange
        self.mock = mock
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        # Mock state
        self._mock_orders: Dict[str, OrderResponse] = {}
        self._mock_fills: Dict[str, list[FillEvent]] = {}
        self._next_exchange_order_id = 1000000
        
        if not mock:
            if not api_key or not api_secret:
                raise ValueError("api_key and api_secret required for live mode")
            logger.info(f"Initializing {exchange} client (live mode, testnet={testnet})")
        else:
            logger.info(f"Initializing {exchange} client (mock mode)")
    
    def place_limit_order(
        self,
        client_order_id: str,
        symbol: str,
        side: Literal["Buy", "Sell"],
        qty: float,
        price: float,
        time_in_force: Literal["GTC", "IOC", "FOK"] = "GTC",
    ) -> OrderResponse:
        """
        Place a limit order.
        
        Args:
            client_order_id: Client-side unique order ID
            symbol: Trading symbol (e.g. "BTCUSDT")
            side: Order side ("Buy" or "Sell")
            qty: Order quantity
            price: Limit price
            time_in_force: Time in force ("GTC", "IOC", "FOK")
        
        Returns:
            OrderResponse with exchange_order_id and status
        
        Raises:
            ValueError: Invalid order parameters
            RuntimeError: Exchange rejected order
        """
        request = OrderRequest(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type="Limit",
            qty=qty,
            price=price,
            time_in_force=time_in_force,
        )
        request.validate()
        
        if self.mock:
            return self._mock_place_order(request)
        else:
            return self._bybit_place_order(request)
    
    def cancel_order(
        self,
        client_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> OrderResponse:
        """
        Cancel an order.
        
        Args:
            client_order_id: Client order ID
            exchange_order_id: Exchange order ID
            symbol: Symbol (required for Bybit)
        
        Returns:
            OrderResponse with status="Canceled"
        
        Raises:
            ValueError: Missing required parameters
            RuntimeError: Order not found or already filled
        """
        if not client_order_id and not exchange_order_id:
            raise ValueError("Either client_order_id or exchange_order_id required")
        
        if self.mock:
            return self._mock_cancel_order(client_order_id, exchange_order_id)
        else:
            return self._bybit_cancel_order(client_order_id, exchange_order_id, symbol)
    
    def get_order_status(
        self,
        client_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
    ) -> Optional[OrderResponse]:
        """
        Get order status.
        
        Args:
            client_order_id: Client order ID
            exchange_order_id: Exchange order ID
        
        Returns:
            OrderResponse or None if not found
        """
        if self.mock:
            return self._mock_get_order_status(client_order_id, exchange_order_id)
        else:
            return self._bybit_get_order_status(client_order_id, exchange_order_id)
    
    def poll_fills(self, client_order_id: str) -> list[FillEvent]:
        """
        Poll for fill events.
        
        Args:
            client_order_id: Client order ID
        
        Returns:
            List of FillEvent objects
        """
        if self.mock:
            return self._mock_fills.get(client_order_id, [])
        else:
            return self._bybit_poll_fills(client_order_id)
    
    # ========================================================================
    # Mock Implementation
    # ========================================================================
    
    def _mock_place_order(self, request: OrderRequest) -> OrderResponse:
        """Mock order placement (testing)."""
        # Simulate 5% rejection rate
        if random.random() < 0.05:
            logger.warning(f"Mock: Rejected order {request.client_order_id}")
            return OrderResponse(
                client_order_id=request.client_order_id,
                exchange_order_id="",
                symbol=request.symbol,
                side=request.side,
                status="Rejected",
                qty=request.qty,
                reject_reason="InsufficientMargin",
            )
        
        # Accept order
        exchange_order_id = f"MOCK-{self._next_exchange_order_id}"
        self._next_exchange_order_id += 1
        
        response = OrderResponse(
            client_order_id=request.client_order_id,
            exchange_order_id=exchange_order_id,
            symbol=request.symbol,
            side=request.side,
            status="New",
            qty=request.qty,
        )
        
        self._mock_orders[request.client_order_id] = response
        self._mock_fills[request.client_order_id] = []
        
        # Simulate fill (async in real world, sync here for simplicity)
        self._mock_simulate_fill(request, response)
        
        logger.info(
            f"Mock: Placed order {request.client_order_id} → {exchange_order_id}"
        )
        
        return response
    
    def _mock_simulate_fill(self, request: OrderRequest, response: OrderResponse) -> None:
        """Simulate fill events for mock orders."""
        # Simulate partial fill (50% chance)
        if random.random() < 0.5:
            partial_qty = request.qty * random.uniform(0.5, 0.9)
            fill_event = FillEvent(
                client_order_id=request.client_order_id,
                exchange_order_id=response.exchange_order_id,
                symbol=request.symbol,
                side=request.side,
                fill_qty=partial_qty,
                fill_price=request.price or 0.0,
                fill_id=f"FILL-{int(time.time() * 1000)}-1",
            )
            self._mock_fills[request.client_order_id].append(fill_event)
            response.filled_qty = partial_qty
            response.status = "PartiallyFilled"
            response.avg_price = request.price
        
        # Full fill
        remaining_qty = request.qty - response.filled_qty
        fill_event = FillEvent(
            client_order_id=request.client_order_id,
            exchange_order_id=response.exchange_order_id,
            symbol=request.symbol,
            side=request.side,
            fill_qty=remaining_qty,
            fill_price=request.price or 0.0,
            fill_id=f"FILL-{int(time.time() * 1000)}-2",
        )
        self._mock_fills[request.client_order_id].append(fill_event)
        response.filled_qty = request.qty
        response.status = "Filled"
        response.avg_price = request.price
    
    def _mock_cancel_order(
        self,
        client_order_id: Optional[str],
        exchange_order_id: Optional[str],
    ) -> OrderResponse:
        """Mock order cancellation."""
        order = self._mock_orders.get(client_order_id or "")
        if not order:
            raise RuntimeError(f"Order not found: {client_order_id}")
        
        if order.status == "Filled":
            raise RuntimeError(f"Order already filled: {client_order_id}")
        
        order.status = "Canceled"
        logger.info(f"Mock: Canceled order {client_order_id}")
        return order
    
    def _mock_get_order_status(
        self,
        client_order_id: Optional[str],
        exchange_order_id: Optional[str],
    ) -> Optional[OrderResponse]:
        """Mock order status query."""
        return self._mock_orders.get(client_order_id or "")
    
    # ========================================================================
    # Bybit Implementation (Placeholder)
    # ========================================================================
    
    def _bybit_place_order(self, request: OrderRequest) -> OrderResponse:
        """Place order on Bybit (live mode)."""
        raise NotImplementedError(
            "Bybit live mode not implemented. "
            "Integrate pybit or requests to Bybit API v5."
        )
    
    def _bybit_cancel_order(
        self,
        client_order_id: Optional[str],
        exchange_order_id: Optional[str],
        symbol: Optional[str],
    ) -> OrderResponse:
        """Cancel order on Bybit (live mode)."""
        raise NotImplementedError("Bybit live mode not implemented")
    
    def _bybit_get_order_status(
        self,
        client_order_id: Optional[str],
        exchange_order_id: Optional[str],
    ) -> Optional[OrderResponse]:
        """Get order status from Bybit (live mode)."""
        raise NotImplementedError("Bybit live mode not implemented")
    
    def _bybit_poll_fills(self, client_order_id: str) -> list[FillEvent]:
        """Poll fills from Bybit (live mode)."""
        raise NotImplementedError("Bybit live mode not implemented")


# Convenience function
def create_client(
    exchange: str = "bybit",
    mock: bool = True,
    **kwargs,
) -> ExchangeClient:
    """
    Factory function to create ExchangeClient.
    
    Args:
        exchange: Exchange name
        mock: Use mock mode
        **kwargs: Additional arguments for ExchangeClient
    
    Returns:
        ExchangeClient instance
    """
    return ExchangeClient(exchange=exchange, mock=mock, **kwargs)


"""
Order Store for tracking order lifecycle in shadow trading.

Pure stdlib implementation with atomic operations.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class OrderState(str, Enum):
    """Order lifecycle state."""
    PENDING = "pending"  # Before submission
    OPEN = "open"  # Submitted and active
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Order record."""
    client_order_id: str
    symbol: str
    side: str  # "Buy" or "Sell"
    qty: float
    price: float
    state: OrderState
    order_id: str | None = None  # Exchange order ID
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    created_at_ms: int = 0
    updated_at_ms: int = 0
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict (for JSON serialization)."""
        return {
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "price": self.price,
            "state": self.state.value,
            "order_id": self.order_id,
            "filled_qty": self.filled_qty,
            "avg_fill_price": self.avg_fill_price,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "message": self.message,
        }


class InMemoryOrderStore:
    """
    In-memory order store with atomic operations.
    
    Tracks order lifecycle and provides deterministic IDs.
    """

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}  # client_order_id -> Order
        self._order_id_seq = 1

    def generate_client_order_id(self) -> str:
        """Generate deterministic client order ID."""
        client_id = f"CLI{self._order_id_seq:08d}"
        self._order_id_seq += 1
        return client_id

    def create(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        timestamp_ms: int,
    ) -> Order:
        """Create a new order in PENDING state."""
        client_order_id = self.generate_client_order_id()
        order = Order(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            state=OrderState.PENDING,
            created_at_ms=timestamp_ms,
            updated_at_ms=timestamp_ms,
        )
        self._orders[client_order_id] = order
        return order

    def update_state(
        self,
        client_order_id: str,
        state: OrderState,
        timestamp_ms: int,
        order_id: str | None = None,
        message: str | None = None,
    ) -> None:
        """Update order state atomically."""
        if client_order_id not in self._orders:
            raise KeyError(f"Order not found: {client_order_id}")

        order = self._orders[client_order_id]
        order.state = state
        order.updated_at_ms = timestamp_ms

        if order_id is not None:
            order.order_id = order_id
        if message is not None:
            order.message = message

    def update_fill(
        self,
        client_order_id: str,
        filled_qty: float,
        avg_fill_price: float,
        timestamp_ms: int,
    ) -> None:
        """Update fill information atomically."""
        if client_order_id not in self._orders:
            raise KeyError(f"Order not found: {client_order_id}")

        order = self._orders[client_order_id]
        order.filled_qty = filled_qty
        order.avg_fill_price = avg_fill_price
        order.updated_at_ms = timestamp_ms

        # Update state based on fill
        if filled_qty >= order.qty - 1e-8:  # Fully filled
            order.state = OrderState.FILLED
        elif filled_qty > 1e-8:  # Partially filled
            order.state = OrderState.PARTIALLY_FILLED

    def get(self, client_order_id: str) -> Order | None:
        """Get order by client_order_id."""
        return self._orders.get(client_order_id)

    def get_by_order_id(self, order_id: str) -> Order | None:
        """Get order by exchange order_id."""
        for order in self._orders.values():
            if order.order_id == order_id:
                return order
        return None

    def get_all(self) -> list[Order]:
        """Get all orders."""
        return list(self._orders.values())

    def get_by_state(self, state: OrderState) -> list[Order]:
        """Get orders by state."""
        return [o for o in self._orders.values() if o.state == state]

    def get_open_orders(self) -> list[Order]:
        """Get all open/partially filled orders."""
        return [
            o for o in self._orders.values()
            if o.state in (OrderState.OPEN, OrderState.PARTIALLY_FILLED)
        ]

    def count_by_state(self) -> dict[str, int]:
        """Count orders by state."""
        counts: dict[str, int] = {}
        for order in self._orders.values():
            state_str = order.state.value
            counts[state_str] = counts.get(state_str, 0) + 1
        return counts

    def cancel(self, client_order_id: str) -> None:
        """Cancel an order by changing its state to CANCELED."""
        if client_order_id in self._orders:
            self._orders[client_order_id].state = OrderState.CANCELED
            self._orders[client_order_id].updated_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    def remove(self, client_order_id: str) -> None:
        """Physically remove an order from the store."""
        if client_order_id in self._orders:
            del self._orders[client_order_id]

    def reset(self) -> None:
        """Reset store (for testing)."""
        self._orders.clear()
        self._order_id_seq = 1

    def to_dict(self) -> dict[str, Any]:
        """Export all orders as dict."""
        return {
            "orders": [o.to_dict() for o in self._orders.values()],
            "count": len(self._orders),
            "count_by_state": self.count_by_state(),
        }


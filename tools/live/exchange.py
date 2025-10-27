"""
Exchange Client Interface and Fake Implementation for Shadow Trading.

Pure stdlib implementation with deterministic behavior for testing.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, Iterator


class Side(str, Enum):
    """Order side."""
    BUY = "Buy"
    SELL = "Sell"


class OrderStatus(str, Enum):
    """Order status on exchange."""
    PENDING = "Pending"
    OPEN = "Open"
    FILLED = "Filled"
    PARTIALLY_FILLED = "PartiallyFilled"
    CANCELED = "Canceled"
    REJECTED = "Rejected"


@dataclass
class PlaceOrderRequest:
    """Request to place a limit order."""
    client_order_id: str
    symbol: str
    side: Side
    qty: float
    price: float


@dataclass
class PlaceOrderResponse:
    """Response from place order."""
    success: bool
    order_id: str | None
    status: OrderStatus
    message: str | None = None


@dataclass
class FillEvent:
    """Fill event from exchange."""
    order_id: str
    symbol: str
    side: Side
    price: float
    qty: float
    timestamp_ms: int


@dataclass
class OpenOrder:
    """Open order on exchange."""
    order_id: str
    client_order_id: str
    symbol: str
    side: Side
    qty: float
    filled_qty: float
    price: float
    status: OrderStatus


@dataclass
class Position:
    """Position on exchange."""
    symbol: str
    qty: float  # Positive for long, negative for short
    avg_entry_price: float


class IExchangeClient(Protocol):
    """Exchange client interface."""

    def place_limit(self, req: PlaceOrderRequest) -> PlaceOrderResponse:
        """Place a limit order."""
        ...

    def cancel(self, order_id: str) -> bool:
        """Cancel an order. Returns True if successful."""
        ...

    def get_open_orders(self, symbol: str | None = None) -> list[OpenOrder]:
        """Get open orders."""
        ...

    def get_positions(self) -> list[Position]:
        """Get current positions."""
        ...

    def stream_fills(self) -> Iterator[FillEvent]:
        """Stream fill events (generator)."""
        ...


class FakeExchangeClient:
    """
    Fake exchange client for shadow trading with deterministic behavior.
    
    Parameters:
    - fill_rate: Probability that an order will be filled (0.0-1.0)
    - reject_rate: Probability that an order will be rejected (0.0-1.0)
    - latency_ms: Simulated latency in milliseconds
    - partial_fill_rate: Probability of partial fill (0.0-1.0)
    - seed: Random seed for determinism
    """

    def __init__(
        self,
        fill_rate: float = 0.8,
        reject_rate: float = 0.05,
        latency_ms: int = 100,
        partial_fill_rate: float = 0.1,
        seed: int | None = None,
    ):
        self.fill_rate = fill_rate
        self.reject_rate = reject_rate
        self.latency_ms = latency_ms
        self.partial_fill_rate = partial_fill_rate
        
        # Deterministic RNG
        self._rng = random.Random(seed if seed is not None else 42)
        
        # Internal state
        self._order_id_seq = 1
        self._orders: dict[str, OpenOrder] = {}
        self._positions: dict[str, float] = {}  # symbol -> qty
        self._pending_fills: list[FillEvent] = []

    def _get_now_ms(self) -> int:
        """Get current timestamp in ms, respecting MM_FREEZE_UTC_ISO."""
        freeze_iso = os.getenv("MM_FREEZE_UTC_ISO")
        if freeze_iso:
            dt = datetime.fromisoformat(freeze_iso.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        return int(time.time() * 1000)

    def place_limit(self, req: PlaceOrderRequest) -> PlaceOrderResponse:
        """Place a limit order with simulated behavior."""
        # Simulate latency
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000.0)

        # Check if rejected
        if self._rng.random() < self.reject_rate:
            return PlaceOrderResponse(
                success=False,
                order_id=None,
                status=OrderStatus.REJECTED,
                message="Simulated rejection",
            )

        # Generate order ID
        order_id = f"ORD{self._order_id_seq:06d}"
        self._order_id_seq += 1

        # Create order
        order = OpenOrder(
            order_id=order_id,
            client_order_id=req.client_order_id,
            symbol=req.symbol,
            side=req.side,
            qty=req.qty,
            filled_qty=0.0,
            price=req.price,
            status=OrderStatus.OPEN,
        )
        self._orders[order_id] = order

        # Decide if it will be filled
        if self._rng.random() < self.fill_rate:
            # Check for partial fill
            if self._rng.random() < self.partial_fill_rate:
                # Partial fill (50-90%)
                fill_pct = 0.5 + self._rng.random() * 0.4
                fill_qty = req.qty * fill_pct
                self._schedule_fill(order_id, req.symbol, req.side, req.price, fill_qty)
                order.filled_qty = fill_qty
                order.status = OrderStatus.PARTIALLY_FILLED
            else:
                # Full fill
                self._schedule_fill(order_id, req.symbol, req.side, req.price, req.qty)
                order.filled_qty = req.qty
                order.status = OrderStatus.FILLED

        return PlaceOrderResponse(
            success=True,
            order_id=order_id,
            status=order.status,
        )

    def _schedule_fill(
        self, order_id: str, symbol: str, side: Side, price: float, qty: float
    ) -> None:
        """Schedule a fill event."""
        fill = FillEvent(
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=price,
            qty=qty,
            timestamp_ms=self._get_now_ms(),
        )
        self._pending_fills.append(fill)

        # Update position
        if symbol not in self._positions:
            self._positions[symbol] = 0.0
        
        if side == Side.BUY:
            self._positions[symbol] += qty
        else:
            self._positions[symbol] -= qty

    def cancel(self, order_id: str) -> bool:
        """Cancel an order."""
        if order_id not in self._orders:
            return False

        order = self._orders[order_id]
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
            return False

        order.status = OrderStatus.CANCELED
        return True

    def get_open_orders(self, symbol: str | None = None) -> list[OpenOrder]:
        """Get open orders."""
        orders = []
        for order in self._orders.values():
            if order.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED):
                if symbol is None or order.symbol == symbol:
                    orders.append(order)
        return orders

    def get_positions(self) -> list[Position]:
        """Get current positions."""
        positions = []
        for symbol, qty in sorted(self._positions.items()):
            if abs(qty) > 1e-8:  # Filter near-zero positions
                # Calculate average entry price (simplified)
                avg_price = 50000.0 if "BTC" in symbol else 3000.0
                positions.append(Position(symbol=symbol, qty=qty, avg_entry_price=avg_price))
        return positions

    def stream_fills(self) -> Iterator[FillEvent]:
        """Stream fill events (generator)."""
        while self._pending_fills:
            yield self._pending_fills.pop(0)

    def reset(self) -> None:
        """Reset state (for testing)."""
        self._order_id_seq = 1
        self._orders.clear()
        self._positions.clear()
        self._pending_fills.clear()


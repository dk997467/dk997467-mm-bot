"""
Order State Machine — FSM for order lifecycle management.

Order States:
- Pending: Order submitted, waiting for exchange confirmation
- New: Order accepted by exchange, active in order book
- PartiallyFilled: Order partially filled
- Filled: Order fully filled
- Canceled: Order canceled (by user or exchange)
- Rejected: Order rejected by exchange

State Transitions:
    Pending → New (on ack)
    Pending → Rejected (on reject)
    New → PartiallyFilled (on partial fill)
    New → Filled (on full fill)
    New → Canceled (on cancel)
    PartiallyFilled → Filled (on remaining fill)
    PartiallyFilled → Canceled (on cancel)

Events:
- OrderAck: Exchange acknowledged order
- OrderReject: Exchange rejected order
- PartialFill: Partial fill received
- FullFill: Order fully filled
- CancelRequest: User requested cancel
- CancelAck: Exchange confirmed cancel
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Literal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class OrderState(str, Enum):
    """Order states."""
    PENDING = "Pending"
    NEW = "New"
    PARTIALLY_FILLED = "PartiallyFilled"
    FILLED = "Filled"
    CANCELED = "Canceled"
    REJECTED = "Rejected"


class EventType(str, Enum):
    """Event types."""
    ORDER_ACK = "OrderAck"
    ORDER_REJECT = "OrderReject"
    PARTIAL_FILL = "PartialFill"
    FULL_FILL = "FullFill"
    CANCEL_REQUEST = "CancelRequest"
    CANCEL_ACK = "CancelAck"


@dataclass
class OrderEvent:
    """Order event (state transition trigger)."""
    
    event_type: EventType
    client_order_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    exchange_order_id: Optional[str] = None
    fill_qty: Optional[float] = None
    fill_price: Optional[float] = None
    reject_reason: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dict for serialization."""
        return {
            "event_type": self.event_type.value,
            "client_order_id": self.client_order_id,
            "timestamp": self.timestamp,
            "exchange_order_id": self.exchange_order_id,
            "fill_qty": self.fill_qty,
            "fill_price": self.fill_price,
            "reject_reason": self.reject_reason,
            "metadata": self.metadata,
        }


@dataclass
class OrderStateRecord:
    """Order state record (current state + history)."""
    
    client_order_id: str
    current_state: OrderState
    symbol: str
    side: str
    qty: float
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    exchange_order_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    events: List[OrderEvent] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dict for serialization."""
        return {
            "client_order_id": self.client_order_id,
            "current_state": self.current_state.value,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "filled_qty": self.filled_qty,
            "avg_price": self.avg_price,
            "exchange_order_id": self.exchange_order_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "events": [e.to_dict() for e in self.events],
        }


class OrderStateMachine:
    """
    Order state machine for lifecycle management.
    
    Features:
    - State validation and transitions
    - Event history tracking
    - Persistence hooks (for Redis/file storage)
    - Structured logging for all transitions
    
    Usage:
        fsm = OrderStateMachine()
        
        # Initialize order
        fsm.create_order("order-1", "BTCUSDT", "Buy", 0.01)
        
        # Handle events
        fsm.handle_event(OrderEvent(EventType.ORDER_ACK, "order-1", exchange_order_id="123"))
        fsm.handle_event(OrderEvent(EventType.PARTIAL_FILL, "order-1", fill_qty=0.005))
        fsm.handle_event(OrderEvent(EventType.FULL_FILL, "order-1", fill_qty=0.005))
    """
    
    # Valid state transitions
    TRANSITIONS = {
        OrderState.PENDING: {
            EventType.ORDER_ACK: OrderState.NEW,
            EventType.ORDER_REJECT: OrderState.REJECTED,
        },
        OrderState.NEW: {
            EventType.PARTIAL_FILL: OrderState.PARTIALLY_FILLED,
            EventType.FULL_FILL: OrderState.FILLED,
            EventType.CANCEL_ACK: OrderState.CANCELED,
        },
        OrderState.PARTIALLY_FILLED: {
            EventType.PARTIAL_FILL: OrderState.PARTIALLY_FILLED,  # Additional partial fill
            EventType.FULL_FILL: OrderState.FILLED,
            EventType.CANCEL_ACK: OrderState.CANCELED,
        },
        # Terminal states (no transitions)
        OrderState.FILLED: {},
        OrderState.CANCELED: {},
        OrderState.REJECTED: {},
    }
    
    def __init__(self):
        """Initialize state machine."""
        self._orders: Dict[str, OrderStateRecord] = {}
        logger.info("OrderStateMachine initialized")
    
    def create_order(
        self,
        client_order_id: str,
        symbol: str,
        side: Literal["Buy", "Sell"],
        qty: float,
    ) -> OrderStateRecord:
        """
        Create a new order (initial state: Pending).
        
        Args:
            client_order_id: Client order ID
            symbol: Trading symbol
            side: Order side
            qty: Order quantity
        
        Returns:
            OrderStateRecord
        
        Raises:
            ValueError: Order already exists
        """
        if client_order_id in self._orders:
            raise ValueError(f"Order already exists: {client_order_id}")
        
        record = OrderStateRecord(
            client_order_id=client_order_id,
            current_state=OrderState.PENDING,
            symbol=symbol,
            side=side,
            qty=qty,
        )
        
        self._orders[client_order_id] = record
        
        logger.info(
            f"Order created: {client_order_id} [{symbol} {side} {qty}] → {OrderState.PENDING.value}"
        )
        
        return record
    
    def handle_event(self, event: OrderEvent) -> OrderStateRecord:
        """
        Handle order event (trigger state transition).
        
        Args:
            event: OrderEvent to process
        
        Returns:
            Updated OrderStateRecord
        
        Raises:
            ValueError: Order not found or invalid transition
        """
        client_order_id = event.client_order_id
        
        # Get order
        record = self._orders.get(client_order_id)
        if not record:
            raise ValueError(f"Order not found: {client_order_id}")
        
        current_state = record.current_state
        
        # Validate transition
        valid_events = self.TRANSITIONS.get(current_state, {})
        if event.event_type not in valid_events:
            raise ValueError(
                f"Invalid transition: {current_state.value} + {event.event_type.value}"
            )
        
        # Transition to new state
        new_state = valid_events[event.event_type]
        old_state = record.current_state
        record.current_state = new_state
        record.updated_at = datetime.now(timezone.utc).isoformat()
        
        # Update order details based on event
        self._apply_event_to_record(record, event)
        
        # Record event
        record.events.append(event)
        
        logger.info(
            f"State transition: {client_order_id} "
            f"{old_state.value} → {new_state.value} "
            f"(event={event.event_type.value})"
        )
        
        return record
    
    def _apply_event_to_record(self, record: OrderStateRecord, event: OrderEvent) -> None:
        """Apply event data to order record."""
        if event.event_type == EventType.ORDER_ACK:
            record.exchange_order_id = event.exchange_order_id
        
        elif event.event_type == EventType.ORDER_REJECT:
            # Rejection metadata stored in event
            pass
        
        elif event.event_type in (EventType.PARTIAL_FILL, EventType.FULL_FILL):
            if event.fill_qty:
                record.filled_qty += event.fill_qty
                
                # Update average price
                if event.fill_price:
                    if record.avg_price is None:
                        record.avg_price = event.fill_price
                    else:
                        # Weighted average
                        total_filled = record.filled_qty
                        prev_filled = total_filled - event.fill_qty
                        record.avg_price = (
                            (record.avg_price * prev_filled + event.fill_price * event.fill_qty)
                            / total_filled
                        )
        
        elif event.event_type == EventType.CANCEL_ACK:
            # Cancellation confirmed
            pass
    
    def get_order(self, client_order_id: str) -> Optional[OrderStateRecord]:
        """
        Get order state record.
        
        Args:
            client_order_id: Client order ID
        
        Returns:
            OrderStateRecord or None if not found
        """
        return self._orders.get(client_order_id)
    
    def get_all_orders(self) -> Dict[str, OrderStateRecord]:
        """
        Get all order state records.
        
        Returns:
            Dict mapping client_order_id to OrderStateRecord
        """
        return self._orders.copy()
    
    def get_orders_by_state(self, state: OrderState) -> List[OrderStateRecord]:
        """
        Get orders in a specific state.
        
        Args:
            state: OrderState to filter by
        
        Returns:
            List of OrderStateRecord
        """
        return [
            record for record in self._orders.values()
            if record.current_state == state
        ]
    
    def get_active_orders(self) -> List[OrderStateRecord]:
        """
        Get active orders (Pending, New, PartiallyFilled).
        
        Returns:
            List of OrderStateRecord
        """
        active_states = {OrderState.PENDING, OrderState.NEW, OrderState.PARTIALLY_FILLED}
        return [
            record for record in self._orders.values()
            if record.current_state in active_states
        ]
    
    def get_terminal_orders(self) -> List[OrderStateRecord]:
        """
        Get terminal orders (Filled, Canceled, Rejected).
        
        Returns:
            List of OrderStateRecord
        """
        terminal_states = {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}
        return [
            record for record in self._orders.values()
            if record.current_state in terminal_states
        ]
    
    def persist_to_dict(self) -> Dict:
        """
        Serialize all orders to dict (for persistence).
        
        Returns:
            Dict representation of all orders
        """
        return {
            "orders": {
                client_order_id: record.to_dict()
                for client_order_id, record in self._orders.items()
            },
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
        }
    
    def restore_from_dict(self, data: Dict) -> None:
        """
        Restore orders from dict (after restart).
        
        Args:
            data: Dict from persist_to_dict()
        """
        orders_data = data.get("orders", {})
        
        for client_order_id, order_dict in orders_data.items():
            # Reconstruct OrderStateRecord
            events = [
                OrderEvent(
                    event_type=EventType(e["event_type"]),
                    client_order_id=e["client_order_id"],
                    timestamp=e["timestamp"],
                    exchange_order_id=e.get("exchange_order_id"),
                    fill_qty=e.get("fill_qty"),
                    fill_price=e.get("fill_price"),
                    reject_reason=e.get("reject_reason"),
                    metadata=e.get("metadata", {}),
                )
                for e in order_dict.get("events", [])
            ]
            
            record = OrderStateRecord(
                client_order_id=order_dict["client_order_id"],
                current_state=OrderState(order_dict["current_state"]),
                symbol=order_dict["symbol"],
                side=order_dict["side"],
                qty=order_dict["qty"],
                filled_qty=order_dict.get("filled_qty", 0.0),
                avg_price=order_dict.get("avg_price"),
                exchange_order_id=order_dict.get("exchange_order_id"),
                created_at=order_dict["created_at"],
                updated_at=order_dict["updated_at"],
                events=events,
            )
            
            self._orders[client_order_id] = record
        
        logger.info(f"Restored {len(self._orders)} orders from persistence")


# Convenience function
def create_fsm() -> OrderStateMachine:
    """
    Factory function to create OrderStateMachine.
    
    Returns:
        OrderStateMachine instance
    """
    return OrderStateMachine()


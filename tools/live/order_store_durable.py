"""
Durable order store with Redis backend and disk snapshots.

Extends InMemoryOrderStore with:
- RedisKV as primary storage
- Idempotency keys for all mutations
- Periodic snapshots to disk (atomic append-only)
- Recovery on restart
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.live.order_store import Order, OrderState, InMemoryOrderStore
from tools.state.redis_client import RedisKV


@dataclass
class IdempotentResult:
    """Result of an idempotent operation."""
    success: bool
    order: Order | None
    was_duplicate: bool
    message: str


class DurableOrderStore:
    """
    Durable order store with Redis backend and idempotency.
    
    Keys:
    - orders:{id} -> Order JSON
    - orders:open -> Set of open order IDs
    - orders:by_symbol:{sym} -> Set of order IDs for symbol
    - idem:{key} -> Cached result for idempotency
    
    Snapshots:
    - artifacts/state/orders.jsonl (append-only)
    """

    def __init__(
        self,
        redis: RedisKV | None = None,
        snapshot_dir: str | Path | None = None,
        clock: Callable[[], float] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize durable order store.
        
        Args:
            redis: RedisKV instance for storage
            snapshot_dir: Directory for disk snapshots
            clock: Optional injectable clock for deterministic testing
            **kwargs: Additional kwargs for backward compatibility (redis_client, state_dir)
        """
        # Backward-compatible aliases
        if redis is None and "redis_client" in kwargs:
            redis = kwargs.pop("redis_client")
        
        # Accept legacy 'state_dir' spelling
        if snapshot_dir is None and "state_dir" in kwargs:
            snapshot_dir = kwargs.pop("state_dir")
        
        # Defaults
        if redis is None:
            raise ValueError("redis or redis_client must be provided")
        if snapshot_dir is None:
            snapshot_dir = "artifacts/state"
        
        self.redis = redis
        self.snapshot_dir = Path(snapshot_dir)
        self._clock = clock
        self._order_id_seq = 1
        
        # Create snapshot directory if needed
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_file = self.snapshot_dir / "orders.jsonl"

    def generate_client_order_id(self) -> str:
        """Generate deterministic client order ID."""
        client_id = f"CLI{self._order_id_seq:08d}"
        self._order_id_seq += 1
        return client_id

    def _serialize_order(self, order: Order) -> dict[str, Any]:
        """Serialize order to dict."""
        return order.to_dict()

    def _deserialize_order(self, data: dict[str, Any]) -> Order:
        """Deserialize dict to Order."""
        # Convert state string to OrderState enum
        state = OrderState(data["state"])
        return Order(
            client_order_id=data["client_order_id"],
            symbol=data["symbol"],
            side=data["side"],
            qty=data["qty"],
            price=data["price"],
            state=state,
            order_id=data.get("order_id"),
            filled_qty=data.get("filled_qty", 0.0),
            avg_fill_price=data.get("avg_fill_price", 0.0),
            created_at_ms=data.get("created_at_ms", 0),
            updated_at_ms=data.get("updated_at_ms", 0),
            message=data.get("message"),
        )

    def _snapshot_order(self, order: Order) -> None:
        """Append order to disk snapshot (atomic)."""
        line = json.dumps(order.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        
        # Atomic append
        with open(self.snapshot_file, "a", encoding="utf-8") as f:
            f.write(line)

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        idem_key: str,
        timestamp_ms: int | None = None,
    ) -> IdempotentResult:
        """
        Place order idempotently.
        
        Args:
            symbol: Trading symbol
            side: "Buy" or "Sell"
            qty: Quantity
            price: Price
            idem_key: Idempotency key (e.g., "place:CLI00000001:v1")
            timestamp_ms: Optional timestamp (defaults to clock())
            
        Returns:
            IdempotentResult with order and duplicate flag
        """
        # Use clock if timestamp not provided
        if timestamp_ms is None:
            if self._clock is not None:
                timestamp_ms = int(self._clock() * 1000)  # clock() returns seconds
            else:
                import time
                timestamp_ms = int(time.time() * 1000)
        # Check idempotency cache
        cached = self.redis.get(f"idem:{idem_key}")
        if cached:
            # This is a duplicate request, return cached result
            result_data = json.loads(cached)
            order_data = result_data.get("order")
            if order_data:
                order = self._deserialize_order(order_data)
                return IdempotentResult(
                    success=result_data["success"],
                    order=order,
                    was_duplicate=True,
                    message=result_data["message"] + " (cached)",
                )
        
        # Generate client order ID
        client_order_id = self.generate_client_order_id()
        
        # Create order
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
        
        # Store in Redis
        order_key = f"orders:{client_order_id}"
        self.redis.set(order_key, self._serialize_order(order))
        
        # Add to symbol index
        symbol_key = f"orders:by_symbol:{symbol}"
        self.redis.sadd(symbol_key, client_order_id)
        
        # Snapshot to disk
        self._snapshot_order(order)
        
        # Cache result for idempotency (24h TTL)
        result = IdempotentResult(
            success=True,
            order=order,
            was_duplicate=False,
            message=f"Order placed: {client_order_id}",
        )
        cache_data = {
            "success": result.success,
            "order": self._serialize_order(order) if order else None,
            "message": result.message,
        }
        self.redis.set(f"idem:{idem_key}", cache_data, ex=86400)
        
        return result

    def update_order_state(
        self,
        client_order_id: str,
        state: OrderState,
        idem_key: str,
        timestamp_ms: int | None = None,
        order_id: str | None = None,
        message: str | None = None,
    ) -> IdempotentResult:
        """
        Update order state idempotently.
        
        Args:
            client_order_id: Client order ID
            state: New state
            idem_key: Idempotency key
            timestamp_ms: Optional timestamp (defaults to clock())
            order_id: Optional exchange order ID
            message: Optional message
            
        Returns:
            IdempotentResult
        """
        # Use clock if timestamp not provided
        if timestamp_ms is None:
            if self._clock is not None:
                timestamp_ms = int(self._clock() * 1000)  # clock() returns seconds
            else:
                import time
                timestamp_ms = int(time.time() * 1000)
        # Check idempotency cache
        cached = self.redis.get(f"idem:{idem_key}")
        if cached:
            result_data = json.loads(cached)
            order_data = result_data.get("order")
            if order_data:
                order = self._deserialize_order(order_data)
                return IdempotentResult(
                    success=result_data["success"],
                    order=order,
                    was_duplicate=True,
                    message=result_data["message"] + " (cached)",
                )
        
        # Get order
        order_key = f"orders:{client_order_id}"
        order_data = self.redis.get(order_key)
        if not order_data:
            result = IdempotentResult(
                success=False,
                order=None,
                was_duplicate=False,
                message=f"Order not found: {client_order_id}",
            )
            # Cache negative result
            cache_data = {"success": False, "order": None, "message": result.message}
            self.redis.set(f"idem:{idem_key}", cache_data, ex=86400)
            return result
        
        order = self._deserialize_order(json.loads(order_data))
        
        # Update state
        old_state = order.state
        order.state = state
        order.updated_at_ms = timestamp_ms
        if order_id:
            order.order_id = order_id
        if message:
            order.message = message
        
        # Save back to Redis
        self.redis.set(order_key, self._serialize_order(order))
        
        # Update indexes
        if old_state in (OrderState.OPEN, OrderState.PARTIALLY_FILLED) and state not in (OrderState.OPEN, OrderState.PARTIALLY_FILLED):
            # Order closed, remove from open set
            self.redis.srem("orders:open", client_order_id)
        elif old_state not in (OrderState.OPEN, OrderState.PARTIALLY_FILLED) and state in (OrderState.OPEN, OrderState.PARTIALLY_FILLED):
            # Order opened, add to open set
            self.redis.sadd("orders:open", client_order_id)
        
        # Snapshot
        self._snapshot_order(order)
        
        # Cache result
        result = IdempotentResult(
            success=True,
            order=order,
            was_duplicate=False,
            message=f"Order state updated: {client_order_id} -> {state.value}",
        )
        cache_data = {
            "success": result.success,
            "order": self._serialize_order(order),
            "message": result.message,
        }
        self.redis.set(f"idem:{idem_key}", cache_data, ex=86400)
        
        return result

    def update_fill(
        self,
        client_order_id: str,
        filled_qty: float,
        avg_fill_price: float,
        idem_key: str,
        timestamp_ms: int | None = None,
    ) -> IdempotentResult:
        """
        Update fill information idempotently.
        
        Args:
            client_order_id: Client order ID
            filled_qty: Filled quantity
            avg_fill_price: Average fill price
            idem_key: Idempotency key
            timestamp_ms: Optional timestamp (defaults to clock())
            
        Returns:
            IdempotentResult
        """
        # Use clock if timestamp not provided
        if timestamp_ms is None:
            if self._clock is not None:
                timestamp_ms = int(self._clock() * 1000)  # clock() returns seconds
            else:
                import time
                timestamp_ms = int(time.time() * 1000)
        # Check idempotency cache
        cached = self.redis.get(f"idem:{idem_key}")
        if cached:
            result_data = json.loads(cached)
            order_data = result_data.get("order")
            if order_data:
                order = self._deserialize_order(order_data)
                return IdempotentResult(
                    success=result_data["success"],
                    order=order,
                    was_duplicate=True,
                    message=result_data["message"] + " (cached)",
                )
        
        # Get order
        order_key = f"orders:{client_order_id}"
        order_data = self.redis.get(order_key)
        if not order_data:
            result = IdempotentResult(
                success=False,
                order=None,
                was_duplicate=False,
                message=f"Order not found: {client_order_id}",
            )
            cache_data = {"success": False, "order": None, "message": result.message}
            self.redis.set(f"idem:{idem_key}", cache_data, ex=86400)
            return result
        
        order = self._deserialize_order(json.loads(order_data))
        
        # Update fill info
        order.filled_qty = filled_qty
        order.avg_fill_price = avg_fill_price
        order.updated_at_ms = timestamp_ms
        
        # Update state based on fill
        if filled_qty >= order.qty - 1e-8:
            order.state = OrderState.FILLED
            self.redis.srem("orders:open", client_order_id)
        elif filled_qty > 1e-8:
            order.state = OrderState.PARTIALLY_FILLED
            self.redis.sadd("orders:open", client_order_id)
        
        # Save
        self.redis.set(order_key, self._serialize_order(order))
        
        # Snapshot
        self._snapshot_order(order)
        
        # Cache result
        result = IdempotentResult(
            success=True,
            order=order,
            was_duplicate=False,
            message=f"Fill updated: {client_order_id} {filled_qty}@{avg_fill_price}",
        )
        cache_data = {
            "success": result.success,
            "order": self._serialize_order(order),
            "message": result.message,
        }
        self.redis.set(f"idem:{idem_key}", cache_data, ex=86400)
        
        return result

    def get_order(self, client_order_id: str) -> Order | None:
        """Get order by client_order_id."""
        order_key = f"orders:{client_order_id}"
        order_data = self.redis.get(order_key)
        if not order_data:
            return None
        return self._deserialize_order(json.loads(order_data))

    def get_open_orders(self) -> list[Order]:
        """Get all open/partially filled orders."""
        open_ids = self.redis.smembers("orders:open")
        orders = []
        for client_order_id in open_ids:
            order = self.get_order(client_order_id)
            if order:
                orders.append(order)
        return orders

    def get_orders_by_symbol(self, symbol: str) -> list[Order]:
        """Get all orders for a symbol."""
        symbol_key = f"orders:by_symbol:{symbol}"
        order_ids = self.redis.smembers(symbol_key)
        orders = []
        for client_order_id in order_ids:
            order = self.get_order(client_order_id)
            if order:
                orders.append(order)
        return orders

    def cancel_all_open(self, idem_key: str, timestamp_ms: int | None = None) -> IdempotentResult:
        """
        Cancel all open orders idempotently.
        
        Args:
            idem_key: Idempotency key (e.g., "cancel_all:freeze_20240101_120000")
            timestamp_ms: Optional timestamp (defaults to clock())
            
        Returns:
            IdempotentResult with count of canceled orders
        """
        # Use clock if timestamp not provided
        if timestamp_ms is None:
            if self._clock is not None:
                timestamp_ms = int(self._clock() * 1000)  # clock() returns seconds
            else:
                import time
                timestamp_ms = int(time.time() * 1000)
        # Check idempotency cache
        cached = self.redis.get(f"idem:{idem_key}")
        if cached:
            result_data = json.loads(cached)
            return IdempotentResult(
                success=result_data["success"],
                order=None,
                was_duplicate=True,
                message=result_data["message"] + " (cached)",
            )
        
        # Get all open orders
        open_orders = self.get_open_orders()
        canceled_count = 0
        
        for order in open_orders:
            # Cancel each order
            order.state = OrderState.CANCELED
            order.updated_at_ms = timestamp_ms
            
            order_key = f"orders:{order.client_order_id}"
            self.redis.set(order_key, self._serialize_order(order))
            self.redis.srem("orders:open", order.client_order_id)
            
            # Snapshot
            self._snapshot_order(order)
            canceled_count += 1
        
        # Cache result
        result = IdempotentResult(
            success=True,
            order=None,
            was_duplicate=False,
            message=f"Canceled {canceled_count} open orders",
        )
        cache_data = {
            "success": result.success,
            "order": None,
            "message": result.message,
        }
        self.redis.set(f"idem:{idem_key}", cache_data, ex=86400)
        
        return result

    def recover_from_snapshot(self) -> int:
        """
        Recover orders from disk snapshot.
        
        Returns:
            Number of orders recovered
        """
        if not self.snapshot_file.exists():
            return 0
        
        recovered = 0
        with open(self.snapshot_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                
                order_data = json.loads(line)
                order = self._deserialize_order(order_data)
                
                # Store in Redis
                order_key = f"orders:{order.client_order_id}"
                self.redis.set(order_key, self._serialize_order(order))
                
                # Update indexes
                symbol_key = f"orders:by_symbol:{order.symbol}"
                self.redis.sadd(symbol_key, order.client_order_id)
                
                if order.state in (OrderState.OPEN, OrderState.PARTIALLY_FILLED):
                    self.redis.sadd("orders:open", order.client_order_id)
                
                recovered += 1
                
                # Track max order ID for sequence
                if order.client_order_id.startswith("CLI"):
                    try:
                        order_num = int(order.client_order_id[3:])
                        self._order_id_seq = max(self._order_id_seq, order_num + 1)
                    except ValueError:
                        pass
        
        return recovered

    def save_snapshot(self) -> None:
        """
        Persist current orders snapshot into snapshot_dir in deterministic JSON.
        Best-effort: never raise if snapshotting fails.
        """
        try:
            import time as _time
            
            # Get all orders from Redis
            all_orders = {}
            cursor = 0
            while True:
                cursor, keys = self.redis.scan(cursor, match="orders:CLI*", count=100)
                for key in keys:
                    order_data = self.redis.get(key)
                    if order_data:
                        order = self._deserialize_order(json.loads(order_data))
                        cid = order.client_order_id
                        all_orders[cid] = {
                            "symbol": order.symbol,
                            "side": order.side,
                            "qty": order.qty,
                            "price": order.price,
                            "state": order.state.value if hasattr(order.state, "value") else str(order.state),
                            "updated_at_ms": order.updated_at_ms,
                            "order_id": order.order_id,
                            "client_order_id": cid,
                        }
                
                if cursor == 0:
                    break
            
            # Determine timestamp
            if self._clock is not None and callable(self._clock):
                now_ms = int(self._clock() * 1000)
            else:
                now_ms = int(_time.time() * 1000)
            
            # Write to JSON snapshot
            snapshot_path = self.snapshot_dir / "orders_snapshot.json"
            data = {
                "ts_ms": now_ms,
                "orders": all_orders
            }
            
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        except Exception:
            # Best-effort: never raise
            pass

    def clear_snapshot(self) -> None:
        """Clear disk snapshot (for testing)."""
        if self.snapshot_file.exists():
            self.snapshot_file.unlink()

    def count_by_state(self) -> dict[str, int]:
        """Count orders by state."""
        counts: dict[str, int] = {}
        
        # Scan all order keys
        cursor = 0
        while True:
            cursor, keys = self.redis.scan(cursor, match="orders:CLI*", count=100)
            for key in keys:
                order_data = self.redis.get(key)
                if order_data:
                    order = self._deserialize_order(json.loads(order_data))
                    state_str = order.state.value
                    counts[state_str] = counts.get(state_str, 0) + 1
            
            if cursor == 0:
                break
        
        return counts


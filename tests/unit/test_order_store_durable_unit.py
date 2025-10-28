"""
Unit tests for DurableOrderStore with idempotency.

Tests:
- Idempotent place_order
- Idempotent update_order_state
- Idempotent update_fill
- Idempotent cancel_all_open
- Snapshot to disk
- Recovery from snapshot
- Index maintenance (orders:open, orders:by_symbol)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tools.live.order_store import OrderState
from tools.live.order_store_durable import DurableOrderStore
from tools.state.redis_client import RedisKV


class FakeClock:
    """Fake clock for deterministic testing."""
    
    def __init__(self, start_time: float = 1000.0):
        self.current_time = start_time
    
    def __call__(self) -> float:
        return self.current_time
    
    def advance(self, seconds: float) -> None:
        """Advance clock by seconds."""
        self.current_time += seconds


@pytest.fixture
def temp_snapshot_dir():
    """Create temporary directory for snapshots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def durable_store(temp_snapshot_dir):
    """Create DurableOrderStore with in-memory Redis."""
    clock = FakeClock()
    redis = RedisKV(no_network=True, clock=clock)
    store = DurableOrderStore(redis=redis, snapshot_dir=temp_snapshot_dir, clock=clock)
    return store


def test_durable_place_order_basic(durable_store):
    """Test basic order placement."""
    result = durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:test001:v1",
    )
    
    assert result.success
    assert result.order is not None
    assert result.order.client_order_id == "CLI00000001"
    assert result.order.symbol == "BTCUSDT"
    assert result.order.side == "Buy"
    assert result.order.qty == 0.01
    assert result.order.price == 50000.0
    assert result.order.state == OrderState.PENDING
    assert not result.was_duplicate


def test_durable_place_order_idempotency(durable_store):
    """Test idempotent order placement (duplicate detection)."""
    # Place order first time
    result1 = durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:dup001:v1",
    )
    
    assert result1.success
    assert not result1.was_duplicate
    order_id1 = result1.order.client_order_id
    
    # Place same order again (duplicate idem_key)
    result2 = durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=2000,
        idem_key="place:dup001:v1",  # Same idem_key
    )
    
    assert result2.success
    assert result2.was_duplicate
    assert result2.order.client_order_id == order_id1  # Same order returned
    assert "(cached)" in result2.message


def test_durable_update_order_state(durable_store):
    """Test updating order state."""
    # Place order
    place_result = durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:test002:v1",
    )
    
    client_order_id = place_result.order.client_order_id
    
    # Update to OPEN state
    update_result = durable_store.update_order_state(
        client_order_id=client_order_id,
        state=OrderState.OPEN,
        timestamp_ms=2000,
        idem_key="update:test002:open:v1",
        order_id="EXC123456",
    )
    
    assert update_result.success
    assert not update_result.was_duplicate
    assert update_result.order.state == OrderState.OPEN
    assert update_result.order.order_id == "EXC123456"


def test_durable_update_order_state_idempotency(durable_store):
    """Test idempotent order state update."""
    # Place and update order
    place_result = durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:test003:v1",
    )
    
    client_order_id = place_result.order.client_order_id
    
    # First update
    update1 = durable_store.update_order_state(
        client_order_id=client_order_id,
        state=OrderState.OPEN,
        timestamp_ms=2000,
        idem_key="update:test003:open:v1",
    )
    
    assert update1.success
    assert not update1.was_duplicate
    
    # Duplicate update (same idem_key)
    update2 = durable_store.update_order_state(
        client_order_id=client_order_id,
        state=OrderState.OPEN,
        timestamp_ms=3000,
        idem_key="update:test003:open:v1",  # Same idem_key
    )
    
    assert update2.success
    assert update2.was_duplicate
    assert "(cached)" in update2.message


def test_durable_update_fill(durable_store):
    """Test updating fill information."""
    # Place order
    place_result = durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:test004:v1",
    )
    
    client_order_id = place_result.order.client_order_id
    
    # Update fill (partial)
    fill_result = durable_store.update_fill(
        client_order_id=client_order_id,
        filled_qty=0.005,
        avg_fill_price=50005.0,
        timestamp_ms=2000,
        idem_key="fill:test004:partial:v1",
    )
    
    assert fill_result.success
    assert not fill_result.was_duplicate
    assert fill_result.order.filled_qty == 0.005
    assert fill_result.order.avg_fill_price == 50005.0
    assert fill_result.order.state == OrderState.PARTIALLY_FILLED


def test_durable_update_fill_complete(durable_store):
    """Test complete fill (state -> FILLED)."""
    # Place order
    place_result = durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:test005:v1",
    )
    
    client_order_id = place_result.order.client_order_id
    
    # Complete fill
    fill_result = durable_store.update_fill(
        client_order_id=client_order_id,
        filled_qty=0.01,  # Fully filled
        avg_fill_price=50010.0,
        timestamp_ms=2000,
        idem_key="fill:test005:complete:v1",
    )
    
    assert fill_result.success
    assert fill_result.order.state == OrderState.FILLED


def test_durable_get_order(durable_store):
    """Test retrieving order by client_order_id."""
    # Place order
    place_result = durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:test006:v1",
    )
    
    client_order_id = place_result.order.client_order_id
    
    # Retrieve order
    order = durable_store.get_order(client_order_id)
    assert order is not None
    assert order.client_order_id == client_order_id
    assert order.symbol == "BTCUSDT"
    
    # Non-existent order
    assert durable_store.get_order("NONEXISTENT") is None


def test_durable_get_open_orders(durable_store):
    """Test retrieving open orders."""
    # Place multiple orders
    for i in range(3):
        durable_store.place_order(
            symbol="BTCUSDT",
            side="Buy",
            qty=0.01,
            price=50000.0 + i * 100,
            timestamp_ms=1000 + i,
            idem_key=f"place:test_open_{i}:v1",
        )
    
    # Initially no open orders (all PENDING)
    open_orders = durable_store.get_open_orders()
    assert len(open_orders) == 0
    
    # Update first two to OPEN
    durable_store.update_order_state(
        client_order_id="CLI00000001",
        state=OrderState.OPEN,
        timestamp_ms=2000,
        idem_key="update:open_1:v1",
    )
    
    durable_store.update_order_state(
        client_order_id="CLI00000002",
        state=OrderState.OPEN,
        timestamp_ms=2001,
        idem_key="update:open_2:v1",
    )
    
    # Should have 2 open orders
    open_orders = durable_store.get_open_orders()
    assert len(open_orders) == 2


def test_durable_get_orders_by_symbol(durable_store):
    """Test retrieving orders by symbol."""
    # Place orders for different symbols
    durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:btc1:v1",
    )
    
    durable_store.place_order(
        symbol="BTCUSDT",
        side="Sell",
        qty=0.01,
        price=51000.0,
        timestamp_ms=1001,
        idem_key="place:btc2:v1",
    )
    
    durable_store.place_order(
        symbol="ETHUSDT",
        side="Buy",
        qty=0.1,
        price=3000.0,
        timestamp_ms=1002,
        idem_key="place:eth1:v1",
    )
    
    # Get BTC orders
    btc_orders = durable_store.get_orders_by_symbol("BTCUSDT")
    assert len(btc_orders) == 2
    
    # Get ETH orders
    eth_orders = durable_store.get_orders_by_symbol("ETHUSDT")
    assert len(eth_orders) == 1


def test_durable_cancel_all_open(durable_store):
    """Test canceling all open orders."""
    # Place and open orders
    for i in range(3):
        result = durable_store.place_order(
            symbol="BTCUSDT",
            side="Buy",
            qty=0.01,
            price=50000.0 + i * 100,
            timestamp_ms=1000 + i,
            idem_key=f"place:cancel_test_{i}:v1",
        )
        
        durable_store.update_order_state(
            client_order_id=result.order.client_order_id,
            state=OrderState.OPEN,
            timestamp_ms=2000 + i,
            idem_key=f"update:cancel_test_{i}:v1",
        )
    
    # Cancel all
    cancel_result = durable_store.cancel_all_open(
        timestamp_ms=3000,
        idem_key="cancel_all:freeze_001:v1",
    )
    
    assert cancel_result.success
    assert not cancel_result.was_duplicate
    assert "Canceled 3 open orders" in cancel_result.message
    
    # Verify no open orders remain
    open_orders = durable_store.get_open_orders()
    assert len(open_orders) == 0


def test_durable_cancel_all_open_idempotency(durable_store):
    """Test idempotent cancel_all_open."""
    # Place and open orders
    result = durable_store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:cancel_idem:v1",
    )
    
    durable_store.update_order_state(
        client_order_id=result.order.client_order_id,
        state=OrderState.OPEN,
        timestamp_ms=2000,
        idem_key="update:cancel_idem:v1",
    )
    
    # First cancel_all
    cancel1 = durable_store.cancel_all_open(
        timestamp_ms=3000,
        idem_key="cancel_all:freeze_idem:v1",
    )
    
    assert cancel1.success
    assert not cancel1.was_duplicate
    
    # Duplicate cancel_all (same idem_key)
    cancel2 = durable_store.cancel_all_open(
        timestamp_ms=4000,
        idem_key="cancel_all:freeze_idem:v1",  # Same key
    )
    
    assert cancel2.success
    assert cancel2.was_duplicate
    assert "(cached)" in cancel2.message


def test_durable_snapshot_to_disk(temp_snapshot_dir):
    """Test that orders are snapshotted to disk."""
    redis = RedisKV(no_network=True)
    store = DurableOrderStore(redis=redis, snapshot_dir=temp_snapshot_dir)
    
    # Place order (should write to snapshot)
    store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:snapshot_test:v1",
    )
    
    # Check snapshot file exists
    snapshot_file = Path(temp_snapshot_dir) / "orders.jsonl"
    assert snapshot_file.exists()
    
    # Read snapshot
    with open(snapshot_file, "r") as f:
        lines = f.readlines()
    
    assert len(lines) == 1
    order_data = json.loads(lines[0])
    assert order_data["symbol"] == "BTCUSDT"
    assert order_data["client_order_id"] == "CLI00000001"


def test_durable_recover_from_snapshot(temp_snapshot_dir):
    """Test recovery from disk snapshot."""
    redis = RedisKV(no_network=True)
    store1 = DurableOrderStore(redis=redis, snapshot_dir=temp_snapshot_dir)
    
    # Place multiple orders
    for i in range(3):
        result = store1.place_order(
            symbol="BTCUSDT",
            side="Buy",
            qty=0.01,
            price=50000.0 + i * 100,
            timestamp_ms=1000 + i,
            idem_key=f"place:recover_{i}:v1",
        )
        
        if i < 2:
            # Mark first two as OPEN
            store1.update_order_state(
                client_order_id=result.order.client_order_id,
                state=OrderState.OPEN,
                timestamp_ms=2000 + i,
                idem_key=f"update:recover_{i}:v1",
            )
    
    # Create new store with fresh Redis (simulating restart)
    redis2 = RedisKV(no_network=True)
    store2 = DurableOrderStore(redis=redis2, snapshot_dir=temp_snapshot_dir)
    
    # Recover from snapshot
    recovered_count = store2.recover_from_snapshot()
    
    # Each order + each update = 5 lines total (3 places + 2 updates)
    assert recovered_count == 5
    
    # Verify open orders recovered
    open_orders = store2.get_open_orders()
    assert len(open_orders) == 2


def test_durable_count_by_state(durable_store):
    """Test counting orders by state."""
    # Place multiple orders in different states
    for i in range(5):
        result = durable_store.place_order(
            symbol="BTCUSDT",
            side="Buy",
            qty=0.01,
            price=50000.0,
            timestamp_ms=1000 + i,
            idem_key=f"place:count_{i}:v1",
        )
        
        if i < 2:
            # Open
            durable_store.update_order_state(
                client_order_id=result.order.client_order_id,
                state=OrderState.OPEN,
                timestamp_ms=2000 + i,
                idem_key=f"update:count_open_{i}:v1",
            )
        elif i == 2:
            # Filled
            durable_store.update_order_state(
                client_order_id=result.order.client_order_id,
                state=OrderState.FILLED,
                timestamp_ms=2000 + i,
                idem_key=f"update:count_filled_{i}:v1",
            )
        # i=3,4 remain PENDING
    
    counts = durable_store.count_by_state()
    assert counts.get("open", 0) == 2
    assert counts.get("filled", 0) == 1
    assert counts.get("pending", 0) == 2


def test_durable_clear_snapshot(temp_snapshot_dir):
    """Test clearing snapshot file."""
    redis = RedisKV(no_network=True)
    store = DurableOrderStore(redis=redis, snapshot_dir=temp_snapshot_dir)
    
    # Place order
    store.place_order(
        symbol="BTCUSDT",
        side="Buy",
        qty=0.01,
        price=50000.0,
        timestamp_ms=1000,
        idem_key="place:clear_test:v1",
    )
    
    snapshot_file = Path(temp_snapshot_dir) / "orders.jsonl"
    assert snapshot_file.exists()
    
    # Clear snapshot
    store.clear_snapshot()
    assert not snapshot_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


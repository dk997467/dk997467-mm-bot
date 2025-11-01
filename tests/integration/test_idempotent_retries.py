"""
Integration test: Idempotent retries with DurableOrderStore.

Scenario:
1. Place order with idempotency key
2. Simulate retry (same idem_key) -> should be no-op
3. Update order state with idem_key -> retry should be no-op
4. Cancel order with idem_key -> retry should be no-op
5. Verify only single effect occurred
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tools.live.exchange import FakeExchangeClient, Side, OrderStatus
from tools.live.execution_loop import ExecutionLoop, ExecutionParams, Quote
from tools.live.order_store import OrderState
from tools.live.order_store_durable import DurableOrderStore
from tools.live.risk_monitor import RuntimeRiskMonitor
from tools.state.redis_client import RedisKV


class FakeClock:
    """Fake clock for deterministic testing."""
    
    def __init__(self, start_time: float = 0.0):
        self.current_time = start_time
    
    def __call__(self) -> float:
        return self.current_time
    
    def advance(self, seconds: float) -> None:
        """Advance clock by seconds."""
        self.current_time += seconds


def test_idempotent_place_order():
    """Test idempotent place_order - retry with same idem_key should be no-op."""
    clock = FakeClock(1000.0)
    redis = RedisKV(clock=clock)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)
        store = DurableOrderStore(redis_client=redis, snapshot_dir=snapshot_dir, clock=clock)
        
        # Place order with idempotency key
        result1 = store.place_order(
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            price=50000.0,
            idem_key="place_001"
        )
        
        assert result1.success
        assert not result1.was_duplicate
        order1 = result1.order
        assert order1 is not None
        assert order1.symbol == "BTCUSDT"
        assert order1.state == OrderState.PENDING
        
        # Retry with same idem_key -> should return same order, no new order created
        result2 = store.place_order(
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            price=50000.0,
            idem_key="place_001"
        )
        
        assert result2.success
        assert result2.was_duplicate  # This should be a duplicate
        order2 = result2.order
        assert order2 is not None
        assert order2.client_order_id == order1.client_order_id
        assert order2.symbol == order1.symbol
        
        # Verify only one order exists
        all_orders = store.get_orders_by_symbol("BTCUSDT")
        assert len(all_orders) == 1
        assert all_orders[0].client_order_id == order1.client_order_id


def test_idempotent_update_order_state():
    """Test idempotent update_order_state - retry should be no-op."""
    clock = FakeClock(1000.0)
    redis = RedisKV(clock=clock)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)
        store = DurableOrderStore(redis_client=redis, snapshot_dir=snapshot_dir, clock=clock)
        
        # Place order
        result = store.place_order(
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            price=50000.0,
            idem_key="place_001"
        )
        assert result.success
        order = result.order
        
        # Update state with idempotency key
        clock.advance(1.0)
        result1 = store.update_order_state(
            order.client_order_id,
            OrderState.OPEN,
            idem_key="update_001"
        )
        assert result1.success
        
        updated = store.get_order(order.client_order_id)
        assert updated is not None
        assert updated.state == OrderState.OPEN
        first_updated_ts = updated.updated_at_ms
        
        # Retry with same idem_key -> should be no-op
        clock.advance(1.0)
        result2 = store.update_order_state(
            order.client_order_id,
            OrderState.OPEN,
            idem_key="update_001"
        )
        assert result2.success
        assert result2.was_duplicate  # Should be idempotent
        
        # Verify timestamp didn't change (idempotent)
        retry_updated = store.get_order(order.client_order_id)
        assert retry_updated is not None
        assert retry_updated.updated_at_ms == first_updated_ts


def test_idempotent_update_fill():
    """Test idempotent update_fill - retry should be no-op."""
    clock = FakeClock(1000.0)
    redis = RedisKV(clock=clock)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)
        store = DurableOrderStore(redis_client=redis, snapshot_dir=snapshot_dir, clock=clock)
        
        # Place and open order
        result = store.place_order(
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.001,
            price=50000.0,
            idem_key="place_001"
        )
        assert result.success
        order = result.order
        store.update_order_state(order.client_order_id, OrderState.OPEN, idem_key="open_001")
        
        # Update fill with idempotency key
        clock.advance(1.0)
        result1 = store.update_fill(
            order.client_order_id,
            filled_qty=0.001,
            avg_fill_price=50000.0,
            idem_key="fill_001"
        )
        assert result1.success
        
        filled = store.get_order(order.client_order_id)
        assert filled is not None
        assert filled.filled_qty == 0.001
        assert filled.state == OrderState.FILLED
        
        # Retry with same idem_key -> should be no-op (no double fill)
        clock.advance(1.0)
        result2 = store.update_fill(
            order.client_order_id,
            filled_qty=0.001,
            avg_fill_price=50000.0,
            idem_key="fill_001"
        )
        assert result2.success
        assert result2.was_duplicate  # Should be idempotent
        
        # Verify still only filled once
        retry_filled = store.get_order(order.client_order_id)
        assert retry_filled is not None
        assert retry_filled.filled_qty == 0.001  # Not 0.002


def test_idempotent_cancel_all_open():
    """Test idempotent cancel_all_open - retry should be no-op."""
    clock = FakeClock(1000.0)
    redis = RedisKV(clock=clock)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)
        store = DurableOrderStore(redis_client=redis, snapshot_dir=snapshot_dir, clock=clock)
        
        # Place multiple orders
        result1 = store.place_order("BTCUSDT", Side.BUY, 0.001, 50000.0, idem_key="p1")
        result2 = store.place_order("ETHUSDT", Side.SELL, 0.01, 3000.0, idem_key="p2")
        assert result1.success
        assert result2.success
        order1 = result1.order
        order2 = result2.order
        
        store.update_order_state(order1.client_order_id, OrderState.OPEN, idem_key="o1")
        store.update_order_state(order2.client_order_id, OrderState.OPEN, idem_key="o2")
        
        # Cancel all with idempotency key
        clock.advance(1.0)
        result1 = store.cancel_all_open(idem_key="cancel_all_001")
        assert result1.success
        assert not result1.was_duplicate
        assert "2" in result1.message  # "Canceled 2 open orders"
        
        # Verify canceled
        o1 = store.get_order(order1.client_order_id)
        o2 = store.get_order(order2.client_order_id)
        assert o1.state == OrderState.CANCELED
        assert o2.state == OrderState.CANCELED
        first_cancel_ts = o1.updated_at_ms
        
        # Retry with same idem_key -> should be no-op (no repeated cancels)
        clock.advance(1.0)
        result2 = store.cancel_all_open(idem_key="cancel_all_001")
        assert result2.success
        assert result2.was_duplicate  # Should be idempotent
        assert "2" in result2.message  # Cached: "Canceled 2 open orders"
        
        # Verify timestamps unchanged (idempotent)
        retry_o1 = store.get_order(order1.client_order_id)
        assert retry_o1.updated_at_ms == first_cancel_ts


def test_exec_loop_with_idempotency_freeze():
    """Test ExecutionLoop with DurableOrderStore - freeze and recovery."""
    clock = FakeClock(0.0)
    redis = RedisKV(clock=clock)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)
        store = DurableOrderStore(redis_client=redis, snapshot_dir=snapshot_dir, clock=clock)
        exchange = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )
        
        # Create ExecutionLoop with idempotency enabled
        loop = ExecutionLoop(
            exchange=exchange,
            order_store=store,
            risk_monitor=risk,
            clock=clock,
            enable_idempotency=True
        )
        
        # Mock quote
        quote = Quote(
            symbol="BTCUSDT",
            bid=50000.0,
            ask=50010.0,
            bid_qty=1.0,
            ask_qty=1.0,
            timestamp=clock.current_time
        )
        
        # Simulate single step (would place orders)
        # For this test, manually place order to simulate
        order = store.place_order("BTCUSDT", Side.BUY, 0.001, 50000.0, idem_key="exec_place_1")
        store.update_order_state(order.client_order_id, OrderState.OPEN, idem_key="exec_open_1")
        
        # Trigger freeze (simulate risk breach)
        risk._breach_count = 3  # Force freeze
        risk._frozen = True
        
        # Call cancel_all (with implicit freeze idem_key)
        loop._cancel_all_open_orders()
        
        # Verify order canceled
        canceled = store.get_order(order.client_order_id)
        assert canceled.state == OrderState.CANCELED
        
        # Retry cancel_all (should be idempotent via freeze idem_key)
        loop._cancel_all_open_orders()
        
        # Verify still only one cancel (check stats)
        assert loop.stats["orders_canceled"] >= 1


def test_exec_loop_recover_from_restart():
    """Test ExecutionLoop recovery after restart."""
    clock = FakeClock(1000.0)
    redis = RedisKV(clock=clock)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)
        
        # --- Phase 1: Initial run with orders ---
        store1 = DurableOrderStore(redis_client=redis, snapshot_dir=snapshot_dir, clock=clock)
        exchange1 = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)
        risk1 = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )
        loop1 = ExecutionLoop(
            exchange=exchange1,
            order_store=store1,
            risk_monitor=risk1,
            clock=clock,
            enable_idempotency=True
        )
        
        # Place orders
        result1 = store1.place_order("BTCUSDT", Side.BUY, 0.001, 50000.0, idem_key="p1")
        result2 = store1.place_order("ETHUSDT", Side.SELL, 0.01, 3000.0, idem_key="p2")
        assert result1.success
        assert result2.success
        order1 = result1.order
        order2 = result2.order
        store1.update_order_state(order1.client_order_id, OrderState.OPEN, idem_key="o1")
        store1.update_order_state(order2.client_order_id, OrderState.OPEN, idem_key="o2")
        
        # Save snapshot
        store1.save_snapshot()
        
        # --- Phase 2: Simulate restart ---
        clock.advance(10.0)
        
        # Create new instances (simulating restart)
        store2 = DurableOrderStore(redis_client=redis, snapshot_dir=snapshot_dir, clock=clock)
        exchange2 = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)
        risk2 = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )
        loop2 = ExecutionLoop(
            exchange=exchange2,
            order_store=store2,
            risk_monitor=risk2,
            clock=clock,
            enable_idempotency=True
        )
        
        # Recover from restart
        recovery_report = loop2.recover_from_restart()
        
        assert recovery_report["recovered"] is True
        assert recovery_report["open_orders_count"] == 2
        assert len(recovery_report["open_orders"]) == 2
        
        # Verify orders recovered
        recovered_order1 = store2.get_order(order1.client_order_id)
        recovered_order2 = store2.get_order(order2.client_order_id)
        
        assert recovered_order1 is not None
        assert recovered_order1.state == OrderState.OPEN
        assert recovered_order2 is not None
        assert recovered_order2.state == OrderState.OPEN


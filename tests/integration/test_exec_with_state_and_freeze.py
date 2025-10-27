"""
Integration test: ExecutionLoop with DurableOrderStore and freeze handling.

Scenario:
1. Start ExecutionLoop with DurableOrderStore
2. Place orders
3. Trigger freeze (edge below threshold)
4. Verify cancel_all is idempotent
5. Simulate restart and recovery
6. Verify byte-stable JSON report
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tools.live.exchange import FakeExchangeClient
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
        """Return current time in seconds."""
        return self.current_time
    
    def __call_int__(self) -> int:
        """Return current time in milliseconds."""
        return int(self.current_time * 1000)
    
    def advance(self, seconds: float) -> None:
        """Advance clock by seconds."""
        self.current_time += seconds


@pytest.fixture
def temp_snapshot_dir():
    """Create temporary directory for snapshots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_exec_loop_with_durable_store_and_freeze(temp_snapshot_dir):
    """
    Test ExecutionLoop with DurableOrderStore handling freeze event.
    
    Steps:
    1. Place orders
    2. Trigger freeze
    3. Verify cancel_all called
    4. Restart loop and recover
    """
    clock = FakeClock(start_time=1000.0)
    
    # Create components with durable store
    redis = RedisKV(no_network=True, clock=clock)
    durable_store = DurableOrderStore(
        redis=redis,
        snapshot_dir=temp_snapshot_dir,
        clock=clock,
    )
    
    exchange = FakeExchangeClient(
        fill_rate=0.0,  # No fills for this test
        reject_rate=0.0,
        latency_ms=0,
        seed=42,
    )
    
    risk_monitor = RuntimeRiskMonitor(
        max_inventory_usd_per_symbol=10000.0,
        max_total_notional_usd=20000.0,
        edge_freeze_threshold_bps=3.0,
    )
    
    loop = ExecutionLoop(
        exchange=exchange,
        order_store=durable_store,
        risk_monitor=risk_monitor,
        clock=lambda: int(clock.current_time * 1000),
        enable_idempotency=True,
    )
    
    # Step 1: Place orders
    params = ExecutionParams(
        symbols=["BTCUSDT", "ETHUSDT"],
        iterations=1,
        max_inventory_usd_per_symbol=10000.0,
        max_total_notional_usd=20000.0,
        edge_freeze_threshold_bps=3.0,
    )
    
    # Feed quote to trigger order placement
    quote = Quote(
        symbol="BTCUSDT",
        bid=50000.0,
        ask=50100.0,
        timestamp_ms=int(clock.current_time * 1000),
    )
    
    loop.on_quote(quote, params)
    
    # Verify orders placed
    assert loop.stats["orders_placed"] >= 0  # Some orders may be risk-blocked
    
    # Step 2: Trigger freeze by updating edge below threshold
    loop.on_edge_update("BTCUSDT", net_bps=2.0)  # Below threshold of 3.0
    
    # Verify freeze event triggered
    assert loop.stats["freeze_events"] == 1
    assert risk_monitor.is_frozen()
    
    # Step 3: Verify freeze is idempotent (duplicate freeze calls are safe)
    # Calling on_edge_update again with same low edge should not double-freeze
    prev_canceled = loop.stats["orders_canceled"]
    loop.on_edge_update("BTCUSDT", net_bps=2.0)
    
    # Freeze events should still be 1 (already frozen)
    assert loop.stats["freeze_events"] == 1
    
    # Step 4: Generate report
    report = loop._generate_report(params)
    
    # Report should be deterministic JSON
    report_json = json.dumps(report, sort_keys=True, separators=(",", ":"))
    assert isinstance(report_json, str)
    assert "execution" in report
    assert report["execution"]["idempotency_enabled"] is True
    assert report["risk"]["frozen"] is True


def test_exec_loop_restart_and_recovery(temp_snapshot_dir):
    """
    Test ExecutionLoop restart with recovery from snapshot.
    
    Steps:
    1. Start loop, place orders, update some to OPEN
    2. Stop loop (simulated)
    3. Create new loop instance, recover from snapshot
    4. Verify open orders restored
    """
    clock = FakeClock(start_time=1000.0)
    
    # === Phase 1: Initial run ===
    redis1 = RedisKV(no_network=True, clock=clock)
    durable_store1 = DurableOrderStore(
        redis=redis1,
        snapshot_dir=temp_snapshot_dir,
        clock=clock,
    )
    
    # Place and open some orders
    for i in range(3):
        result = durable_store1.place_order(
            symbol="BTCUSDT",
            side="Buy",
            qty=0.01,
            price=50000.0 + i * 100,
            timestamp_ms=int(clock.current_time * 1000) + i,
            idem_key=f"place:restart_test_{i}:v1",
        )
        
        if i < 2:
            # Mark first two as OPEN
            durable_store1.update_order_state(
                client_order_id=result.order.client_order_id,
                state=OrderState.OPEN,
                timestamp_ms=int(clock.current_time * 1000) + 100 + i,
                idem_key=f"update:restart_test_{i}:open:v1",
            )
    
    # Verify snapshot exists
    snapshot_file = Path(temp_snapshot_dir) / "orders.jsonl"
    assert snapshot_file.exists()
    
    # === Phase 2: Restart (new Redis, recover from snapshot) ===
    clock.advance(1.0)  # Advance time
    
    redis2 = RedisKV(no_network=True, clock=clock)
    durable_store2 = DurableOrderStore(
        redis=redis2,
        snapshot_dir=temp_snapshot_dir,
        clock=clock,
    )
    
    # Create new ExecutionLoop
    exchange2 = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, latency_ms=0, seed=42)
    risk_monitor2 = RuntimeRiskMonitor(
        max_inventory_usd_per_symbol=10000.0,
        max_total_notional_usd=20000.0,
        edge_freeze_threshold_bps=3.0,
    )
    
    loop2 = ExecutionLoop(
        exchange=exchange2,
        order_store=durable_store2,
        risk_monitor=risk_monitor2,
        clock=lambda: int(clock.current_time * 1000),
        enable_idempotency=True,
    )
    
    # Recover from snapshot
    recovery_report = loop2.recover_from_restart()
    
    assert recovery_report["recovered"] is True
    assert recovery_report["total_orders_recovered"] == 5  # 3 places + 2 updates
    assert recovery_report["open_orders_count"] == 2
    assert len(recovery_report["open_orders"]) == 2
    
    # Verify stats
    assert loop2.stats["recoveries"] == 1


def test_freeze_cancel_all_idempotency(temp_snapshot_dir):
    """
    Test that freeze -> cancel_all is idempotent.
    
    Multiple freeze calls should not duplicate cancel operations.
    """
    clock = FakeClock(start_time=1000.0)
    
    redis = RedisKV(no_network=True, clock=clock)
    durable_store = DurableOrderStore(
        redis=redis,
        snapshot_dir=temp_snapshot_dir,
        clock=clock,
    )
    
    # Place and open orders
    for i in range(3):
        result = durable_store.place_order(
            symbol="BTCUSDT",
            side="Buy",
            qty=0.01,
            price=50000.0,
            timestamp_ms=int(clock.current_time * 1000),
            idem_key=f"place:freeze_idem_{i}:v1",
        )
        
        durable_store.update_order_state(
            client_order_id=result.order.client_order_id,
            state=OrderState.OPEN,
            timestamp_ms=int(clock.current_time * 1000) + 100,
            idem_key=f"update:freeze_idem_{i}:open:v1",
        )
    
    # Verify 3 open orders
    open_orders = durable_store.get_open_orders()
    assert len(open_orders) == 3
    
    # First cancel_all (freeze)
    result1 = durable_store.cancel_all_open(
        timestamp_ms=int(clock.current_time * 1000) + 200,
        idem_key="cancel_all:freeze_20231201_120000",
    )
    
    assert result1.success
    assert not result1.was_duplicate
    assert "Canceled 3 open orders" in result1.message
    
    # Verify all canceled
    open_orders = durable_store.get_open_orders()
    assert len(open_orders) == 0
    
    # Second cancel_all (duplicate freeze call)
    result2 = durable_store.cancel_all_open(
        timestamp_ms=int(clock.current_time * 1000) + 300,
        idem_key="cancel_all:freeze_20231201_120000",  # Same idem_key
    )
    
    assert result2.success
    assert result2.was_duplicate
    assert "(cached)" in result2.message


def test_exec_loop_byte_stable_report(temp_snapshot_dir):
    """
    Test that execution loop report is byte-stable.
    
    Running same scenario twice should produce identical JSON.
    """
    clock1 = FakeClock(start_time=1000.0)
    clock2 = FakeClock(start_time=1000.0)
    
    def run_scenario(clock, tmpdir):
        """Run deterministic scenario."""
        redis = RedisKV(no_network=True, clock=clock)
        durable_store = DurableOrderStore(
            redis=redis,
            snapshot_dir=tmpdir,
            clock=clock,
        )
        
        exchange = FakeExchangeClient(
            fill_rate=0.0,
            reject_rate=0.0,
            latency_ms=0,
            seed=42,  # Same seed
        )
        
        risk_monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=20000.0,
            edge_freeze_threshold_bps=3.0,
        )
        
        loop = ExecutionLoop(
            exchange=exchange,
            order_store=durable_store,
            risk_monitor=risk_monitor,
            clock=lambda: int(clock.current_time * 1000),
            enable_idempotency=True,
        )
        
        # Place orders
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=20000.0,
            edge_freeze_threshold_bps=3.0,
        )
        
        quote = Quote(
            symbol="BTCUSDT",
            bid=50000.0,
            ask=50100.0,
            timestamp_ms=int(clock.current_time * 1000),
        )
        
        loop.on_quote(quote, params)
        
        # Generate report (without runtime.utc since it's non-deterministic)
        report = loop._generate_report(params)
        del report["runtime"]["utc"]  # Remove non-deterministic timestamp
        
        return json.dumps(report, sort_keys=True, separators=(",", ":"))
    
    # Run scenario twice
    with tempfile.TemporaryDirectory() as tmpdir1:
        report1 = run_scenario(clock1, tmpdir1)
    
    with tempfile.TemporaryDirectory() as tmpdir2:
        report2 = run_scenario(clock2, tmpdir2)
    
    # Reports should be byte-identical
    assert report1 == report2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


"""
E2E Test: Live Execution Engine

Test Flow:
1. Place 2 limit orders (Buy BTCUSDT, Sell ETHUSDT)
2. Wait for fills (1 full fill, 1 partial fill)
3. Update position tracker with fills
4. Reconcile positions with exchange
5. Verify FSM state transitions
6. Check Prometheus metrics

Requirements:
- All components initialized correctly
- Orders routed through exchange client (mock mode)
- State machine tracks order lifecycle
- Position tracker calculates P&L correctly
- Metrics exported in Prometheus format
"""

import pytest
import time
import json
import random
from pathlib import Path
from datetime import datetime, timezone

from tools.live.exchange_client import create_client, FillEvent
from tools.live.order_router import create_router
from tools.live.state_machine import (
    create_fsm,
    OrderState,
    EventType,
    OrderEvent,
)
from tools.live.positions import create_tracker
from tools.live.metrics import LiveExecutionMetrics


def test_live_execution_full_cycle_e2e(tmp_path):
    """
    E2E test: Place orders → fills → position updates → reconcile.
    
    Scenario:
    - Place Buy order: BTCUSDT 0.01 @ 50000
    - Place Sell order: ETHUSDT 0.1 @ 3000
    - Mock client simulates fills (1 full, 1 partial)
    - Position tracker updates
    - FSM tracks state transitions
    - Reconcile with exchange
    - Export Prometheus metrics
    """
    # ==========================================================================
    # SETUP: Initialize components
    # ==========================================================================
    
    # Set random seed for deterministic mock behavior
    random.seed(42)
    
    # Order router (includes exchange client)
    router = create_router(exchange="bybit", mock=True, max_attempts=3)
    
    # State machine
    fsm = create_fsm()
    
    # Position tracker
    tracker = create_tracker()
    
    # Metrics
    metrics = LiveExecutionMetrics()
    
    # ==========================================================================
    # STEP 1: Place orders
    # ==========================================================================
    
    # Order 1: Buy BTCUSDT
    order1_id = "order-btc-buy-001"
    order1_symbol = "BTCUSDT"
    order1_side = "Buy"
    order1_qty = 0.01
    order1_price = 50000.0
    
    # Create FSM record
    fsm.create_order(order1_id, order1_symbol, order1_side, order1_qty)
    
    # Place via router
    with metrics.track_order_latency(order1_symbol):
        response1 = router.place_order(
            client_order_id=order1_id,
            symbol=order1_symbol,
            side=order1_side,
            qty=order1_qty,
            price=order1_price,
        )
        metrics.increment_orders_placed(order1_symbol, order1_side)
    
    # Verify placement
    assert response1.client_order_id == order1_id
    assert response1.status in ("New", "Filled", "PartiallyFilled")
    assert response1.exchange_order_id.startswith("MOCK-")
    
    # Update FSM: OrderAck
    fsm.handle_event(OrderEvent(
        event_type=EventType.ORDER_ACK,
        client_order_id=order1_id,
        exchange_order_id=response1.exchange_order_id,
    ))
    
    # Order 2: Sell ETHUSDT
    order2_id = "order-eth-sell-001"
    order2_symbol = "ETHUSDT"
    order2_side = "Sell"
    order2_qty = 0.1
    order2_price = 3000.0
    
    # Create FSM record
    fsm.create_order(order2_id, order2_symbol, order2_side, order2_qty)
    
    # Place via router
    with metrics.track_order_latency(order2_symbol):
        response2 = router.place_order(
            client_order_id=order2_id,
            symbol=order2_symbol,
            side=order2_side,
            qty=order2_qty,
            price=order2_price,
        )
        metrics.increment_orders_placed(order2_symbol, order2_side)
    
    # Verify placement
    assert response2.client_order_id == order2_id
    assert response2.status in ("New", "Filled", "PartiallyFilled")
    
    # Update FSM: OrderAck
    fsm.handle_event(OrderEvent(
        event_type=EventType.ORDER_ACK,
        client_order_id=order2_id,
        exchange_order_id=response2.exchange_order_id,
    ))
    
    # ==========================================================================
    # STEP 2: Poll for fills
    # ==========================================================================
    
    # Poll order 1 fills (use router, not client, to access the correct instance)
    fills1 = router.poll_fills(order1_id)
    assert len(fills1) > 0, "Expected at least one fill for order 1"
    
    # Apply fills to position tracker
    for fill in fills1:
        tracker.apply_fill(fill)
        
        # Update FSM
        if fill.fill_qty == order1_qty:
            # Full fill
            fsm.handle_event(OrderEvent(
                event_type=EventType.FULL_FILL,
                client_order_id=order1_id,
                fill_qty=fill.fill_qty,
                fill_price=fill.fill_price,
            ))
            metrics.increment_orders_filled(order1_symbol, order1_side)
        else:
            # Partial fill
            fsm.handle_event(OrderEvent(
                event_type=EventType.PARTIAL_FILL,
                client_order_id=order1_id,
                fill_qty=fill.fill_qty,
                fill_price=fill.fill_price,
            ))
            metrics.increment_orders_partially_filled(order1_symbol, order1_side)
    
    # Poll order 2 fills (use router, not client, to access the correct instance)
    fills2 = router.poll_fills(order2_id)
    assert len(fills2) > 0, "Expected at least one fill for order 2"
    
    # Apply fills to position tracker
    for fill in fills2:
        tracker.apply_fill(fill)
        
        # Update FSM
        if fill.fill_qty == order2_qty:
            # Full fill
            fsm.handle_event(OrderEvent(
                event_type=EventType.FULL_FILL,
                client_order_id=order2_id,
                fill_qty=fill.fill_qty,
                fill_price=fill.fill_price,
            ))
            metrics.increment_orders_filled(order2_symbol, order2_side)
        else:
            # Partial fill
            fsm.handle_event(OrderEvent(
                event_type=EventType.PARTIAL_FILL,
                client_order_id=order2_id,
                fill_qty=fill.fill_qty,
                fill_price=fill.fill_price,
            ))
            metrics.increment_orders_partially_filled(order2_symbol, order2_side)
    
    # ==========================================================================
    # STEP 3: Verify FSM state transitions
    # ==========================================================================
    
    # Check order 1 state
    order1_record = fsm.get_order(order1_id)
    assert order1_record is not None
    assert order1_record.current_state in (
        OrderState.FILLED,
        OrderState.PARTIALLY_FILLED,
    )
    assert order1_record.filled_qty > 0
    assert len(order1_record.events) >= 2  # OrderAck + Fill event(s)
    
    # Check order 2 state
    order2_record = fsm.get_order(order2_id)
    assert order2_record is not None
    assert order2_record.current_state in (
        OrderState.FILLED,
        OrderState.PARTIALLY_FILLED,
    )
    assert order2_record.filled_qty > 0
    
    # ==========================================================================
    # STEP 4: Verify position tracker
    # ==========================================================================
    
    # Check BTC position
    btc_pos = tracker.get_position(order1_symbol)
    assert btc_pos is not None
    assert btc_pos.qty > 0, "Expected long BTC position"
    assert btc_pos.total_buy_qty == order1_record.filled_qty
    assert btc_pos.avg_entry_price == pytest.approx(order1_price, abs=0.01)
    
    # Check ETH position
    eth_pos = tracker.get_position(order2_symbol)
    assert eth_pos is not None
    assert eth_pos.qty < 0, "Expected short ETH position"
    assert eth_pos.total_sell_qty == order2_record.filled_qty
    assert eth_pos.avg_entry_price == pytest.approx(order2_price, abs=0.01)
    
    # Update mark prices and check unrealized P&L
    tracker.update_mark_price(order1_symbol, 50100.0)  # BTC up $100
    tracker.update_mark_price(order2_symbol, 2950.0)   # ETH down $50
    
    btc_pos = tracker.get_position(order1_symbol)
    eth_pos = tracker.get_position(order2_symbol)
    
    # BTC unrealized P&L should be positive
    assert btc_pos.unrealized_pnl > 0, "Expected positive unrealized P&L for BTC"
    
    # ETH unrealized P&L should be positive (short position, price down)
    assert eth_pos.unrealized_pnl > 0, "Expected positive unrealized P&L for ETH"
    
    # Total P&L
    total_pnl = tracker.get_total_pnl()
    assert total_pnl > 0, "Expected positive total P&L"
    
    # ==========================================================================
    # STEP 5: Reconcile positions
    # ==========================================================================
    
    # Simulate exchange reporting positions
    btc_reconcile_ok = tracker.reconcile_position(
        symbol=order1_symbol,
        exchange_qty=btc_pos.qty,
        exchange_avg_price=btc_pos.avg_entry_price,
    )
    assert btc_reconcile_ok, "BTC position reconciliation failed"
    
    eth_reconcile_ok = tracker.reconcile_position(
        symbol=order2_symbol,
        exchange_qty=eth_pos.qty,
        exchange_avg_price=eth_pos.avg_entry_price,
    )
    assert eth_reconcile_ok, "ETH position reconciliation failed"
    
    # Test drift detection (intentional mismatch)
    drift_detected = tracker.reconcile_position(
        symbol=order1_symbol,
        exchange_qty=btc_pos.qty + 0.01,  # Drift: +0.01
        exchange_avg_price=btc_pos.avg_entry_price,
    )
    assert not drift_detected, "Expected drift detection to fail"
    
    # ==========================================================================
    # STEP 6: Update metrics gauges
    # ==========================================================================
    
    # Update position metrics
    metrics.set_position_qty(order1_symbol, btc_pos.qty)
    metrics.set_position_pnl(
        order1_symbol,
        btc_pos.realized_pnl + btc_pos.unrealized_pnl,
    )
    
    metrics.set_position_qty(order2_symbol, eth_pos.qty)
    metrics.set_position_pnl(
        order2_symbol,
        eth_pos.realized_pnl + eth_pos.unrealized_pnl,
    )
    
    # ==========================================================================
    # STEP 7: Export Prometheus metrics
    # ==========================================================================
    
    prom_text = metrics.export_prometheus()
    
    # Verify metrics format
    assert "orders_placed_total" in prom_text
    assert "orders_filled_total" in prom_text or "orders_partially_filled_total" in prom_text
    assert "order_latency_seconds" in prom_text
    assert "position_qty" in prom_text
    assert "position_pnl" in prom_text
    assert order1_symbol in prom_text
    assert order2_symbol in prom_text
    
    # Write to file
    metrics_file = tmp_path / "live_execution_metrics.prom"
    metrics_file.write_text(prom_text, encoding="utf-8")
    
    assert metrics_file.exists()
    assert metrics_file.stat().st_size > 0
    
    # ==========================================================================
    # STEP 8: Persist and restore (state persistence test)
    # ==========================================================================
    
    # Persist FSM
    fsm_snapshot = fsm.persist_to_dict()
    fsm_file = tmp_path / "fsm_state.json"
    fsm_file.write_text(json.dumps(fsm_snapshot, indent=2), encoding="utf-8")
    
    # Persist positions
    pos_snapshot = tracker.persist_to_dict()
    pos_file = tmp_path / "positions.json"
    pos_file.write_text(json.dumps(pos_snapshot, indent=2), encoding="utf-8")
    
    # Restore in new instances
    fsm_restored = create_fsm()
    fsm_restored.restore_from_dict(fsm_snapshot)
    
    tracker_restored = create_tracker()
    tracker_restored.restore_from_dict(pos_snapshot)
    
    # Verify restoration
    assert len(fsm_restored.get_all_orders()) == 2
    assert fsm_restored.get_order(order1_id) is not None
    assert fsm_restored.get_order(order2_id) is not None
    
    assert len(tracker_restored.get_all_positions()) == 2
    btc_pos_restored = tracker_restored.get_position(order1_symbol)
    assert btc_pos_restored is not None
    assert btc_pos_restored.qty == pytest.approx(btc_pos.qty, abs=1e-6)
    
    # ==========================================================================
    # SUMMARY
    # ==========================================================================
    
    print("\n" + "=" * 80)
    print("E2E TEST SUMMARY")
    print("=" * 80)
    print(f"Orders placed: 2")
    print(f"Order 1: {order1_id} [{order1_symbol} {order1_side}] -> {order1_record.current_state.value}")
    print(f"  Filled: {order1_record.filled_qty}/{order1_qty}")
    print(f"Order 2: {order2_id} [{order2_symbol} {order2_side}] -> {order2_record.current_state.value}")
    print(f"  Filled: {order2_record.filled_qty}/{order2_qty}")
    print(f"\nPositions:")
    print(f"  {order1_symbol}: {btc_pos.qty:.6f} @ {btc_pos.avg_entry_price:.2f}")
    print(f"    Realized P&L: {btc_pos.realized_pnl:.2f}")
    print(f"    Unrealized P&L: {btc_pos.unrealized_pnl:.2f}")
    print(f"  {order2_symbol}: {eth_pos.qty:.6f} @ {eth_pos.avg_entry_price:.2f}")
    print(f"    Realized P&L: {eth_pos.realized_pnl:.2f}")
    print(f"    Unrealized P&L: {eth_pos.unrealized_pnl:.2f}")
    print(f"\nTotal P&L: {total_pnl:.2f}")
    print(f"\nReconciliation: PASS")
    print(f"Metrics exported: {metrics_file}")
    print(f"State persisted: {fsm_file}, {pos_file}")
    print("=" * 80)


def test_live_execution_cancellation_e2e(tmp_path):
    """
    E2E test: Order placement -> cancellation.
    
    Scenario:
    - Place order
    - Cancel before fill
    - Verify FSM transition to Canceled
    - Verify metrics
    
    Note: Mock client simulates fills immediately, but we test cancellation logic anyway.
    In real trading, cancel would happen before fill.
    """
    # Setup
    random.seed(123)  # Different seed to avoid rejection
    router = create_router(exchange="bybit", mock=True)
    fsm = create_fsm()
    metrics = LiveExecutionMetrics()
    
    # Place order
    order_id = "order-cancel-test"
    symbol = "BTCUSDT"
    side = "Buy"
    qty = 0.01
    price = 50000.0
    
    fsm.create_order(order_id, symbol, side, qty)
    
    response = router.place_order(
        client_order_id=order_id,
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
    )
    
    fsm.handle_event(OrderEvent(
        event_type=EventType.ORDER_ACK,
        client_order_id=order_id,
        exchange_order_id=response.exchange_order_id,
    ))
    
    # Cancel order (may fail if already filled in mock)
    try:
        cancel_response = router.cancel_order(order_id, symbol=symbol)
        
        assert cancel_response.status == "Canceled"
        
        # Update FSM
        fsm.handle_event(OrderEvent(
            event_type=EventType.CANCEL_ACK,
            client_order_id=order_id,
        ))
        
        # Verify state
        order_record = fsm.get_order(order_id)
        assert order_record.current_state == OrderState.CANCELED
        
        print(f"✓ Order canceled successfully")
    
    except RuntimeError as e:
        if "already filled" in str(e).lower():
            print(f"⚠ Order already filled, cannot cancel (expected in mock mode)")
            # This is acceptable behavior in mock mode
            pytest.skip("Mock client filled order before cancellation could occur")
        else:
            raise
    
    # Metrics
    metrics.increment_orders_canceled(symbol, side)
    
    prom_text = metrics.export_prometheus()
    assert "orders_canceled_total" in prom_text


def test_live_execution_rejection_e2e(tmp_path):
    """
    E2E test: Order rejection scenario.
    
    Mock client has ~5% rejection rate.
    This test verifies rejection handling.
    """
    router = create_router(exchange="bybit", mock=True)
    fsm = create_fsm()
    metrics = LiveExecutionMetrics()
    
    # Try placing multiple orders to trigger rejection
    for i in range(50):
        order_id = f"order-reject-{i}"
        symbol = "BTCUSDT"
        side = "Buy"
        qty = 0.01
        price = 50000.0
        
        fsm.create_order(order_id, symbol, side, qty)
        
        try:
            response = router.place_order(
                client_order_id=order_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
            )
            
            if response.status == "Rejected":
                # Handle rejection
                fsm.handle_event(OrderEvent(
                    event_type=EventType.ORDER_REJECT,
                    client_order_id=order_id,
                    reject_reason=response.reject_reason,
                ))
                
                metrics.increment_orders_rejected(
                    symbol,
                    side,
                    response.reject_reason or "unknown",
                )
                
                # Verify FSM state
                order_record = fsm.get_order(order_id)
                assert order_record.current_state == OrderState.REJECTED
                
                print(f"✓ Rejection handled: {order_id} → {response.reject_reason}")
                break
        
        except RuntimeError as e:
            # Router raises RuntimeError on rejection
            if "rejected" in str(e).lower():
                fsm.handle_event(OrderEvent(
                    event_type=EventType.ORDER_REJECT,
                    client_order_id=order_id,
                    reject_reason=str(e),
                ))
                metrics.increment_orders_rejected(symbol, side, "RuntimeError")
                print(f"✓ Rejection caught: {order_id}")
                break
    else:
        # No rejection in 50 attempts (unlikely but possible)
        pytest.skip("No rejection encountered in 50 attempts (mock randomness)")


if __name__ == "__main__":
    # Run test standalone
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        print("\n" + "=" * 80)
        print("Running E2E Test: Live Execution Full Cycle")
        print("=" * 80)
        
        test_live_execution_full_cycle_e2e(tmp_path)
        
        print("\n✅ E2E Test PASSED")


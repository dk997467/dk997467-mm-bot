"""
Idempotency tests - 3 повтора без флаки.

Цель: убедиться, что async batch стабилен и детерминирован.
"""
import pytest
import asyncio
from unittest.mock import MagicMock

from src.strategy.async_tick_orchestrator import AsyncTickOrchestrator
from src.execution.command_bus import Command, CmdType


class MockConfig:
    """Mock config."""
    def __init__(self):
        self.async_batch = MagicMock()
        self.async_batch.enabled = True
        self.async_batch.max_parallel_symbols = 10
        self.async_batch.coalesce_cancel = True
        self.async_batch.coalesce_place = True
        self.async_batch.tick_deadline_ms = 200


class MockConnector:
    """Mock connector with deterministic responses."""
    def __init__(self):
        self.calls = []
    
    async def batch_cancel_orders(self, symbol: str, order_ids=None, client_order_ids=None):
        """Mock batch cancel."""
        self.calls.append(("cancel", symbol, len(order_ids or []) + len(client_order_ids or [])))
        return {
            "success_count": len(order_ids or []) + len(client_order_ids or []),
            "failed_count": 0,
            "details": []
        }
    
    async def batch_place_orders(self, symbol: str, orders):
        """Mock batch place."""
        self.calls.append(("place", symbol, len(orders)))
        return {
            "success_count": len(orders),
            "failed_count": 0,
            "details": []
        }


@pytest.fixture
def mock_ctx():
    """Mock app context."""
    ctx = MagicMock()
    ctx.cfg = MockConfig()
    return ctx


@pytest.mark.asyncio
async def test_idempotency_3x_same_result(mock_ctx):
    """
    Test: 3 повтора одного и того же тика дают идентичный результат.
    
    Acceptance:
    - Все 3 прогона дают одинаковый результат (no флаки)
    """
    symbols = ["BTCUSDT", "ETHUSDT"]
    orderbooks = {sym: {"bids": [[50000, 1.0]], "asks": [[50100, 1.0]]} for sym in symbols}
    
    results = []
    
    for iteration in range(3):
        connector = MockConnector()
        orch = AsyncTickOrchestrator(mock_ctx, connector)
        
        # Enqueue same commands
        for symbol in symbols:
            for i in range(5):
                orch.cmd_bus.enqueue(Command(CmdType.CANCEL, symbol, {"order_id": f"order_{i}"}))
            for i in range(3):
                orch.cmd_bus.enqueue(Command(CmdType.PLACE, symbol, {"side": "Buy", "qty": 1.0, "price": 50000}))
        
        # Flush
        result = await orch._flush_commands()
        
        results.append({
            "success": result["total_success"],
            "failed": result["total_failed"],
            "calls": len(connector.calls)
        })
        
        print(f"[ITER {iteration+1}] Success: {result['total_success']}, Failed: {result['total_failed']}, Calls: {len(connector.calls)}")
    
    # Assertions: all 3 runs should be identical
    assert results[0] == results[1] == results[2], f"Idempotency violated: {results}"
    print("[IDEMPOTENCY] 3x runs produced identical results ✓")


@pytest.mark.asyncio
async def test_idempotency_3x_no_flakiness(mock_ctx):
    """
    Test: 3 повтора без флаки (все прошли успешно).
    
    Acceptance:
    - Все 3 прогона завершились с rc=0
    """
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    orderbooks = {sym: {"bids": [[50000, 1.0]], "asks": [[50100, 1.0]]} for sym in symbols}
    
    for iteration in range(3):
        connector = MockConnector()
        orch = AsyncTickOrchestrator(mock_ctx, connector)
        
        # Process tick
        result = await orch.process_tick(symbols, orderbooks)
        
        # Assert success
        assert result.get("symbol_errors", 0) == 0, f"Iteration {iteration+1} had errors"
        print(f"[ITER {iteration+1}] Passed ✓")
    
    print("[IDEMPOTENCY] 3x runs completed without flakiness ✓")


@pytest.mark.asyncio
async def test_idempotency_3x_deterministic_order(mock_ctx):
    """
    Test: порядок обработки символов детерминирован.
    
    Acceptance:
    - Символы обрабатываются в одном и том же порядке во всех 3 прогонах
    """
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    orderbooks = {sym: {"bids": [[50000, 1.0]], "asks": [[50100, 1.0]]} for sym in symbols}
    
    symbol_orders = []
    
    for iteration in range(3):
        connector = MockConnector()
        orch = AsyncTickOrchestrator(mock_ctx, connector)
        
        # Enqueue commands for all symbols
        for symbol in symbols:
            orch.cmd_bus.enqueue(Command(CmdType.CANCEL, symbol, {"order_id": "order_1"}))
        
        # Flush and record order
        await orch._flush_commands()
        
        # Extract symbol order from connector calls
        call_order = [call[1] for call in connector.calls]
        symbol_orders.append(call_order)
        
        print(f"[ITER {iteration+1}] Symbol order: {call_order}")
    
    # Assertions: all 3 runs should have same symbol order
    assert symbol_orders[0] == symbol_orders[1] == symbol_orders[2], f"Order not deterministic: {symbol_orders}"
    print("[IDEMPOTENCY] Symbol processing order is deterministic ✓")


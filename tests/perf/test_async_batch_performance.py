"""
Performance tests для async batch processing.

Цель: P95(tick) < 200ms, P99 < 250ms при 4+ символах.
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from typing import List

from src.strategy.async_tick_orchestrator import AsyncTickOrchestrator
from src.execution.command_bus import CommandBus, Command, CmdType
from src.common.di import AppContext
from src.connectors.bybit_rest import BybitRESTConnector


class MockConfig:
    """Mock config для тестов."""
    def __init__(self, async_batch_enabled: bool = True):
        self.async_batch = MagicMock()
        self.async_batch.enabled = async_batch_enabled
        self.async_batch.max_parallel_symbols = 10
        self.async_batch.coalesce_cancel = True
        self.async_batch.coalesce_place = True
        self.async_batch.tick_deadline_ms = 200


class MockConnector:
    """Mock connector для batch API."""
    def __init__(self, latency_ms: float = 10.0):
        self.latency_ms = latency_ms
        self.batch_cancel_count = 0
        self.batch_place_count = 0
    
    async def batch_cancel_orders(self, symbol: str, order_ids=None, client_order_ids=None):
        """Mock batch cancel with artificial latency."""
        await asyncio.sleep(self.latency_ms / 1000)
        self.batch_cancel_count += 1
        
        total = len(order_ids or []) + len(client_order_ids or [])
        return {
            "success_count": total,
            "failed_count": 0,
            "details": []
        }
    
    async def batch_place_orders(self, symbol: str, orders: List):
        """Mock batch place with artificial latency."""
        await asyncio.sleep(self.latency_ms / 1000)
        self.batch_place_count += 1
        
        return {
            "success_count": len(orders),
            "failed_count": 0,
            "details": []
        }


@pytest.fixture
def mock_ctx():
    """Mock app context."""
    ctx = MagicMock()
    ctx.cfg = MockConfig(async_batch_enabled=True)
    return ctx


@pytest.fixture
def mock_connector():
    """Mock connector with 10ms latency."""
    return MockConnector(latency_ms=10.0)


@pytest.mark.asyncio
async def test_async_batch_vs_sequential_performance(mock_ctx, mock_connector):
    """
    Test: async batch должен быть быстрее sequential на 4+ символах.
    
    Acceptance:
    - Async mode: P95 < 200ms
    - Sequential mode: P95 > 200ms (baseline)
    """
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT"]
    orderbooks = {sym: {"bids": [[50000, 1.0]], "asks": [[50100, 1.0]]} for sym in symbols}
    
    # Test 1: Sequential mode (baseline)
    mock_ctx.cfg = MockConfig(async_batch_enabled=False)
    orch_seq = AsyncTickOrchestrator(mock_ctx, mock_connector)
    
    durations_seq = []
    for _ in range(10):
        start = time.time()
        await orch_seq.process_tick(symbols, orderbooks)
        durations_seq.append((time.time() - start) * 1000)
    
    p95_seq = sorted(durations_seq)[int(len(durations_seq) * 0.95)]
    
    # Test 2: Async mode
    mock_ctx.cfg = MockConfig(async_batch_enabled=True)
    orch_async = AsyncTickOrchestrator(mock_ctx, mock_connector)
    
    durations_async = []
    for _ in range(10):
        start = time.time()
        await orch_async.process_tick(symbols, orderbooks)
        durations_async.append((time.time() - start) * 1000)
    
    p95_async = sorted(durations_async)[int(len(durations_async) * 0.95)]
    
    # Assertions
    print(f"[PERF] Sequential P95: {p95_seq:.2f}ms")
    print(f"[PERF] Async P95: {p95_async:.2f}ms")
    print(f"[PERF] Speedup: {p95_seq / p95_async:.2f}x")
    
    # Acceptance criteria: Async должен быть существенно быстрее
    assert p95_async < 200, f"Async P95 {p95_async:.2f}ms exceeds target 200ms"
    assert p95_async < p95_seq * 0.6, f"Async not faster than sequential (speedup {p95_seq/p95_async:.2f}x < 1.67x)"


@pytest.mark.asyncio
async def test_async_batch_p99_under_250ms(mock_ctx, mock_connector):
    """
    Test: P99(tick) < 250ms при 4+ символах.
    
    Acceptance:
    - P99 < 250ms
    """
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT"]
    orderbooks = {sym: {"bids": [[50000, 1.0]], "asks": [[50100, 1.0]]} for sym in symbols}
    
    orch = AsyncTickOrchestrator(mock_ctx, mock_connector)
    
    durations = []
    for _ in range(100):  # More iterations for P99
        start = time.time()
        await orch.process_tick(symbols, orderbooks)
        durations.append((time.time() - start) * 1000)
    
    p95 = sorted(durations)[int(len(durations) * 0.95)]
    p99 = sorted(durations)[int(len(durations) * 0.99)]
    
    print(f"[PERF] P95: {p95:.2f}ms, P99: {p99:.2f}ms")
    
    assert p95 < 200, f"P95 {p95:.2f}ms exceeds target 200ms"
    assert p99 < 250, f"P99 {p99:.2f}ms exceeds target 250ms"


@pytest.mark.asyncio
async def test_network_calls_reduction(mock_ctx, mock_connector):
    """
    Test: сетевые вызовы в тике уменьшены на ≥40%.
    
    Acceptance:
    - Async mode: ≤ 0.6 * sequential calls
    """
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT"]
    orderbooks = {sym: {"bids": [[50000, 1.0]], "asks": [[50100, 1.0]]} for sym in symbols}
    
    # Test 1: Sequential (baseline network calls)
    mock_ctx.cfg = MockConfig(async_batch_enabled=False)
    orch_seq = AsyncTickOrchestrator(mock_ctx, mock_connector)
    mock_connector_seq = MockConnector(latency_ms=10.0)
    orch_seq.connector = mock_connector_seq
    
    # Simulate 10 cancel + 10 place per symbol in sequential
    # In reality, this would be 4 symbols * 10 cancel + 4 symbols * 10 place = 80 calls
    # But with batching, it should be 4 batch-cancel + 4 batch-place = 8 calls
    
    # For demo, let's inject commands to bus
    for symbol in symbols:
        for i in range(10):
            orch_seq.cmd_bus.enqueue(Command(CmdType.CANCEL, symbol, {"order_id": f"order_{i}"}))
            orch_seq.cmd_bus.enqueue(Command(CmdType.PLACE, symbol, {"side": "Buy", "qty": 1.0, "price": 50000}))
    
    await orch_seq._flush_commands()
    calls_seq = mock_connector_seq.batch_cancel_count + mock_connector_seq.batch_place_count
    
    # Test 2: Async with batching
    mock_ctx.cfg = MockConfig(async_batch_enabled=True)
    orch_async = AsyncTickOrchestrator(mock_ctx, mock_connector)
    mock_connector_async = MockConnector(latency_ms=10.0)
    orch_async.connector = mock_connector_async
    
    for symbol in symbols:
        for i in range(10):
            orch_async.cmd_bus.enqueue(Command(CmdType.CANCEL, symbol, {"order_id": f"order_{i}"}))
            orch_async.cmd_bus.enqueue(Command(CmdType.PLACE, symbol, {"side": "Buy", "qty": 1.0, "price": 50000}))
    
    await orch_async._flush_commands()
    calls_async = mock_connector_async.batch_cancel_count + mock_connector_async.batch_place_count
    
    print(f"[NET] Sequential calls: {calls_seq}")
    print(f"[NET] Async calls: {calls_async}")
    print(f"[NET] Reduction: {(1 - calls_async / max(1, calls_seq)) * 100:.1f}%")
    
    # Acceptance: ≥40% reduction
    assert calls_async <= calls_seq * 0.6, f"Network calls not reduced by 40% ({calls_async}/{calls_seq})"


@pytest.mark.asyncio
async def test_rollback_to_sequential(mock_ctx, mock_connector):
    """
    Test: feature.async_batch=false возвращает старую последовательную схему.
    
    Acceptance:
    - Rollback работает без ошибок
    - Sequential mode активирован
    """
    symbols = ["BTCUSDT", "ETHUSDT"]
    orderbooks = {sym: {"bids": [[50000, 1.0]], "asks": [[50100, 1.0]]} for sym in symbols}
    
    # Rollback mode
    mock_ctx.cfg = MockConfig(async_batch_enabled=False)
    orch = AsyncTickOrchestrator(mock_ctx, mock_connector)
    
    result = await orch.process_tick(symbols, orderbooks)
    
    assert result["mode"] == "sequential", "Rollback did not activate sequential mode"
    assert result["symbols_processed"] == len(symbols), "Not all symbols processed"
    print("[ROLLBACK] Sequential mode activated successfully")


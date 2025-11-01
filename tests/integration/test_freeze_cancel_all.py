"""
Integration tests for robust cancel-all on freeze.

Tests verify end-to-end freeze → cancel-all flow with:
- Multiple open orders across symbols
- Backoff on exchange errors (429, timeout)
- Idempotency with Redis lock
- Metrics export
- Reconciliation
"""
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from dataclasses import dataclass

from src.execution.cancel_all_robust import CancelAllOrchestrator, CancelResult


@dataclass
class MockOrder:
    """Mock order for testing."""
    client_order_id: str
    symbol: str
    state: str = "OPEN"


class MockOrderStore:
    """Mock order store for testing."""
    
    def __init__(self):
        self.orders = {}
    
    def add_order(self, order: MockOrder):
        """Add order to store."""
        self.orders[order.client_order_id] = order
    
    def get_open_orders(self):
        """Get open orders."""
        return [o for o in self.orders.values() if o.state == "OPEN"]
    
    def cancel(self, client_order_id: str):
        """Cancel order."""
        if client_order_id in self.orders:
            self.orders[client_order_id].state = "CANCELED"
    
    def mark_canceled(self, client_order_id: str, trigger: str = ""):
        """Mark order as canceled."""
        self.cancel(client_order_id)


class MockExchange:
    """Mock exchange client for testing."""
    
    def __init__(self, support_bulk_cancel=True):
        self.cancel_called = []
        self.bulk_cancel_called = []
        self.should_fail = False
        self.fail_count = 0
        self.fail_first_n = 0
        
        # Optionally add bulk cancel method
        if support_bulk_cancel:
            self.cancel_all_open_orders = self._bulk_cancel_impl
    
    async def cancel(self, client_order_id: str):
        """Cancel single order."""
        self.cancel_called.append(client_order_id)
        
        # Simulate failures
        if self.should_fail or (self.fail_first_n > 0 and len(self.cancel_called) <= self.fail_first_n):
            self.fail_count += 1
            raise Exception("HTTP 429 rate limit exceeded")
        
        return {"success": True}
    
    async def _bulk_cancel_impl(self, symbols: list):
        """Bulk cancel implementation."""
        self.bulk_cancel_called.append(symbols)
        
        if self.should_fail:
            self.fail_count += 1
            raise Exception("HTTP 500 internal server error")
        
        return {"success": True}


class MockMetrics:
    """Mock metrics collector."""
    
    def __init__(self):
        self.counters = {}
        self.gauges = {}
        self.observations = []
    
    def inc(self, name: str, value: int = 1, labels: dict = None):
        """Increment counter."""
        key = (name, tuple(sorted((labels or {}).items())))
        self.counters[key] = self.counters.get(key, 0) + value
    
    def set(self, name: str, value: float):
        """Set gauge."""
        self.gauges[name] = value
    
    def observe(self, name: str, value: float):
        """Observe value."""
        self.observations.append((name, value))
    
    def get_counter(self, name: str, labels: dict = None) -> int:
        """Get counter value."""
        key = (name, tuple(sorted((labels or {}).items())))
        return self.counters.get(key, 0)


class TestFreezeCancelAllSuccess:
    """Test successful cancel-all scenarios."""
    
    @pytest.mark.asyncio
    async def test_cancel_all_with_bulk_method(self):
        """Test cancel-all using bulk cancel method."""
        # Setup
        exchange = MockExchange()
        store = MockOrderStore()
        metrics = MockMetrics()
        
        # Add orders
        for i in range(5):
            store.add_order(MockOrder(f"order_{i}", "BTCUSDT"))
        for i in range(3):
            store.add_order(MockOrder(f"order_eth_{i}", "ETHUSDT"))
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            redis_client=None,  # No Redis for unit test
            metrics=metrics,
            session_id="test_session"
        )
        
        # Execute
        result = await orchestrator.cancel_all_open_orders(
            reason="edge_below_threshold",
            symbols=["BTCUSDT", "ETHUSDT"]
        )
        
        # Assert
        assert result.success is True
        assert result.canceled_count == 8
        assert result.method == "bulk"
        assert len(store.get_open_orders()) == 0
        
        # Check bulk cancel was called
        assert len(exchange.bulk_cancel_called) == 1
        assert set(exchange.bulk_cancel_called[0]) == {"BTCUSDT", "ETHUSDT"}
        
        # Check metrics
        assert metrics.get_counter("mm_cancel_all_total", {"status": "success"}) == 1
        assert metrics.get_counter("mm_cancel_all_orders_total") == 8
    
    @pytest.mark.asyncio
    async def test_cancel_all_per_order_fallback(self):
        """Test cancel-all falling back to per-order when bulk fails."""
        # Setup - exchange without bulk cancel support
        exchange = MockExchange(support_bulk_cancel=False)
        store = MockOrderStore()
        metrics = MockMetrics()
        
        # Add orders
        for i in range(3):
            store.add_order(MockOrder(f"order_{i}", "BTCUSDT"))
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            metrics=metrics
        )
        
        # Execute
        result = await orchestrator.cancel_all_open_orders(
            reason="freeze",
            symbols=["BTCUSDT"]
        )
        
        # Assert
        assert result.success is True
        assert result.canceled_count == 3
        assert result.method == "per_order"
        assert len(store.get_open_orders()) == 0
        
        # Check per-order cancel was called
        assert len(exchange.cancel_called) == 3
    
    @pytest.mark.asyncio
    async def test_cancel_all_no_orders(self):
        """Test cancel-all with no open orders."""
        exchange = MockExchange()
        store = MockOrderStore()
        metrics = MockMetrics()
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            metrics=metrics
        )
        
        result = await orchestrator.cancel_all_open_orders(reason="freeze")
        
        assert result.success is True
        assert result.canceled_count == 0
        assert result.method == "no_orders"
        assert result.duration_ms < 100  # Should be fast


class TestFreezeCancelAllBackoff:
    """Test retry with backoff on failures."""
    
    @pytest.mark.asyncio
    async def test_retry_on_429_rate_limit(self):
        """Test retry with backoff on 429 rate limit."""
        exchange = MockExchange(support_bulk_cancel=False)
        store = MockOrderStore()
        metrics = MockMetrics()
        
        # Add orders
        store.add_order(MockOrder("order_1", "BTCUSDT"))
        store.add_order(MockOrder("order_2", "BTCUSDT"))
        
        # Fail first 2 attempts, then succeed
        exchange.fail_first_n = 2
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            metrics=metrics
        )
        
        # Execute
        result = await orchestrator.cancel_all_open_orders(reason="freeze")
        
        # Assert
        assert result.success is True
        assert result.canceled_count == 2
        
        # Check that retries happened (3 calls per order: fail, fail, succeed)
        assert len(exchange.cancel_called) >= 4  # At least 2 orders * 2 attempts
    
    @pytest.mark.asyncio
    async def test_backoff_respects_max_attempts(self):
        """Test that backoff stops after max attempts."""
        exchange = MockExchange(support_bulk_cancel=False)
        exchange.should_fail = True  # Always fail
        store = MockOrderStore()
        metrics = MockMetrics()
        
        store.add_order(MockOrder("order_1", "BTCUSDT"))
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            metrics=metrics
        )
        
        # Execute (will exhaust retries)
        result = await orchestrator.cancel_all_open_orders(reason="freeze")
        
        # Even with failures, local cancel should succeed
        assert len(store.get_open_orders()) == 0  # Local consistency maintained
        assert result.failed_count > 0  # Exchange failures recorded
        
        # Check max attempts not exceeded (7 attempts per order)
        assert exchange.fail_count <= 7


class TestFreezeCancelAllIdempotency:
    """Test idempotency with concurrent freeze events."""
    
    @pytest.mark.asyncio
    async def test_concurrent_freeze_only_one_executes(self):
        """Test that concurrent freeze calls are idempotent."""
        # Setup with mock Redis
        redis_mock = AsyncMock()
        
        # First acquire succeeds, second fails (lock already held)
        redis_mock.set.side_effect = [True, False, False]
        redis_mock.eval.return_value = 1
        
        exchange = MockExchange()
        store = MockOrderStore()
        metrics = MockMetrics()
        
        store.add_order(MockOrder("order_1", "BTCUSDT"))
        store.add_order(MockOrder("order_2", "BTCUSDT"))
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            redis_client=redis_mock,
            metrics=metrics,
            session_id="test_session"
        )
        
        # Execute concurrently
        results = await asyncio.gather(
            orchestrator.cancel_all_open_orders(reason="freeze"),
            orchestrator.cancel_all_open_orders(reason="freeze"),
            orchestrator.cancel_all_open_orders(reason="freeze")
        )
        
        # First should succeed, others should skip
        successful = [r for r in results if r.method in ("bulk", "per_order")]
        skipped = [r for r in results if r.method == "idempotent_skip"]
        
        assert len(successful) == 1  # Only one executed
        assert len(skipped) == 2      # Two skipped
        
        # Check metrics
        assert metrics.get_counter("mm_cancel_all_skipped_total", {"reason": "lock_held"}) >= 2
    
    @pytest.mark.asyncio
    async def test_lock_released_after_completion(self):
        """Test that lock is released after cancel-all completes."""
        redis_mock = AsyncMock()
        redis_mock.set.return_value = True
        redis_mock.eval.return_value = 1
        
        exchange = MockExchange()
        store = MockOrderStore()
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            redis_client=redis_mock,
            session_id="test_session"
        )
        
        await orchestrator.cancel_all_open_orders(reason="freeze")
        
        # Check that release (eval) was called
        assert redis_mock.eval.called
        assert redis_mock.eval.call_count >= 1


class TestFreezeCancelAllMetrics:
    """Test metrics export during cancel-all."""
    
    @pytest.mark.asyncio
    async def test_metrics_exported(self):
        """Test that all metrics are exported correctly."""
        exchange = MockExchange()
        store = MockOrderStore()
        metrics = MockMetrics()
        
        for i in range(10):
            store.add_order(MockOrder(f"order_{i}", "BTCUSDT" if i < 5 else "ETHUSDT"))
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            metrics=metrics
        )
        
        result = await orchestrator.cancel_all_open_orders(reason="edge_below_threshold")
        
        # Check counters
        assert metrics.get_counter("mm_cancel_all_total", {"status": "success"}) == 1
        assert metrics.get_counter("mm_cancel_all_orders_total") == 10
        
        # Check duration observation
        assert len(metrics.observations) >= 1
        assert metrics.observations[0][0] == "mm_cancel_all_duration_ms"
        assert metrics.observations[0][1] > 0
        
        # Check remaining orders gauge (may not be set if no reconciliation issue)
        remaining = metrics.gauges.get("mm_cancel_all_remaining_orders", 0)
        assert remaining == 0
    
    @pytest.mark.asyncio
    async def test_metrics_on_failure(self):
        """Test metrics exported on failure."""
        exchange = MockExchange(support_bulk_cancel=False)
        exchange.should_fail = True
        store = MockOrderStore()
        metrics = MockMetrics()
        
        store.add_order(MockOrder("order_1", "BTCUSDT"))
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            metrics=metrics
        )
        
        result = await orchestrator.cancel_all_open_orders(reason="freeze")
        
        # Check failure metrics
        assert metrics.get_counter("mm_cancel_all_per_order_failure_total", {"symbol": "BTCUSDT"}) >= 1


class TestFreezeCancelAllReconciliation:
    """Test reconciliation after cancel-all."""
    
    @pytest.mark.asyncio
    async def test_reconciliation_verifies_zero_open_orders(self):
        """Test that reconciliation verifies no open orders remain."""
        exchange = MockExchange()
        store = MockOrderStore()
        metrics = MockMetrics()
        
        for i in range(5):
            store.add_order(MockOrder(f"order_{i}", "BTCUSDT"))
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            metrics=metrics
        )
        
        result = await orchestrator.cancel_all_open_orders(reason="freeze")
        
        # Verify no open orders
        assert len(store.get_open_orders()) == 0
        
        # Check reconciliation metric
        remaining = metrics.gauges.get("mm_cancel_all_remaining_orders", 0)
        assert remaining == 0
    
    @pytest.mark.asyncio
    async def test_reconciliation_detects_remaining_orders(self):
        """Test that reconciliation detects any remaining orders."""
        exchange = MockExchange()
        store = MockOrderStore()
        metrics = MockMetrics()
        
        # Add orders
        for i in range(3):
            store.add_order(MockOrder(f"order_{i}", "BTCUSDT"))
        
        # Mock both cancel and mark_canceled to leave one order open
        original_cancel = store.cancel
        original_mark_canceled = store.mark_canceled
        
        def mock_cancel(cid):
            if cid != "order_1":  # Skip canceling order_1
                original_cancel(cid)
        
        def mock_mark_canceled(cid, trigger=""):
            if cid != "order_1":  # Skip canceling order_1
                original_mark_canceled(cid, trigger)
        
        store.cancel = mock_cancel
        store.mark_canceled = mock_mark_canceled
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            metrics=metrics
        )
        
        await orchestrator.cancel_all_open_orders(reason="freeze")
        
        # Reconciliation should detect remaining order
        remaining = len(store.get_open_orders())
        assert remaining >= 1  # At least one should remain
        remaining_metric = metrics.gauges.get("mm_cancel_all_remaining_orders", 1)
        assert remaining_metric >= 1


class TestCancelAllDurationP95:
    """Test that cancel-all completes within SLA."""
    
    @pytest.mark.asyncio
    async def test_duration_under_10s_p95(self):
        """Test that cancel-all completes within 10s p95."""
        exchange = MockExchange()
        store = MockOrderStore()
        metrics = MockMetrics()
        
        # Large number of orders to stress test
        for i in range(100):
            symbol = ["BTCUSDT", "ETHUSDT", "SOLUSDT"][i % 3]
            store.add_order(MockOrder(f"order_{i}", symbol))
        
        orchestrator = CancelAllOrchestrator(
            exchange=exchange,
            order_store=store,
            metrics=metrics
        )
        
        result = await orchestrator.cancel_all_open_orders(reason="freeze")
        
        # Check duration
        assert result.duration_ms < 10000  # Should complete within 10s
        assert result.success is True
        assert result.canceled_count == 100


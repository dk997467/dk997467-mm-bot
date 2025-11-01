"""
Integration test: ExecutionLoop with observability (logs, metrics, health/ready).

Scenario:
1. Start ExecutionLoop with --obs enabled
2. Place orders → check metrics incremented
3. Trigger freeze → check /ready returns 503
4. Verify metrics (/metrics) contain expected data
5. Verify structured logs are emitted
"""

from __future__ import annotations

import io
import json
import time
from http.client import HTTPConnection

import pytest

from tools.live.exchange import FakeExchangeClient
from tools.live.execution_loop import ExecutionLoop, ExecutionParams, Quote
from tools.live.order_store import InMemoryOrderStore
from tools.live.risk_monitor import RuntimeRiskMonitor
from tools.obs import health_server, jsonlog, metrics


class FakeClock:
    """Fake clock for deterministic testing."""
    
    def __init__(self, start_time: int = 1000000):
        self.current_time = start_time
    
    def __call__(self) -> int:
        return self.current_time
    
    def advance(self, ms: int) -> None:
        """Advance clock by milliseconds."""
        self.current_time += ms


def test_exec_loop_with_observability():
    """Test ExecutionLoop with observability enabled."""
    # Reset freeze events counter for test isolation
    from tools.obs import metrics as obs_metrics
    try:
        obs_metrics.FREEZE_EVENTS._values[()] = 0.0
    except Exception:
        pass
    
    clock = FakeClock()
    
    # Create components
    exchange = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)
    order_store = InMemoryOrderStore()
    risk_monitor = RuntimeRiskMonitor(
        max_inventory_usd_per_symbol=10000.0,
        max_total_notional_usd=50000.0,
        edge_freeze_threshold_bps=1.5,
    )
    
    loop = ExecutionLoop(
        exchange=exchange,
        order_store=order_store,
        risk_monitor=risk_monitor,
        clock=clock,
    )
    
    # Capture structured logs
    log_output = io.StringIO()
    logger = jsonlog.get_logger(
        "test",
        output_stream=log_output,
        clock=lambda: "2025-10-27T10:00:00.000000Z",
    )
    
    # Start health server
    class TestHealthProviders:
        """Test health providers."""
        def state_ready(self) -> bool:
            return True
        
        def risk_ready(self) -> bool:
            return not risk_monitor.is_frozen()
        
        def exchange_ready(self) -> bool:
            return True
    
    providers = TestHealthProviders()
    server = health_server.start_server(
        "127.0.0.1",
        18090,
        providers,
        metrics_renderer=metrics.render_prometheus,
    )
    
    try:
        time.sleep(0.1)
        
        # Step 1: Check /health (should always be 200)
        conn = HTTPConnection("127.0.0.1", 18090, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert json.loads(body)["status"] == "ok"
        conn.close()
        
        # Step 2: Check /ready (should be 200, not frozen yet)
        conn = HTTPConnection("127.0.0.1", 18090, timeout=5)
        conn.request("GET", "/ready")
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        data = json.loads(body)
        assert data["status"] == "ok"
        assert data["checks"]["risk"] is True
        conn.close()
        
        # Step 3: Place some orders
        quote = Quote(symbol="BTCUSDT", bid=50000.0, ask=50010.0, timestamp_ms=clock())
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )
        
        loop.on_quote(quote, params)
        
        # Step 4: Check metrics (should have orders_placed incremented)
        conn = HTTPConnection("127.0.0.1", 18090, timeout=5)
        conn.request("GET", "/metrics")
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        
        # Should contain mm_orders_placed_total metric
        assert "mm_orders_placed_total" in body
        # Should have BTCUSDT label
        assert "BTCUSDT" in body
        
        conn.close()
        
        # Step 5: Trigger freeze by setting edge below threshold
        loop.on_edge_update("BTCUSDT", 1.0)  # Below 1.5 threshold
        
        assert risk_monitor.is_frozen()
        
        # Step 6: Check /ready (should be 503, frozen)
        conn = HTTPConnection("127.0.0.1", 18090, timeout=5)
        conn.request("GET", "/ready")
        resp = conn.getresponse()
        assert resp.status == 503
        body = resp.read().decode("utf-8")
        data = json.loads(body)
        assert data["status"] == "fail"
        assert data["checks"]["risk"] is False
        conn.close()
        
        # Step 7: Check metrics for freeze_events
        conn = HTTPConnection("127.0.0.1", 18090, timeout=5)
        conn.request("GET", "/metrics")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        
        assert "mm_freeze_events_total" in body
        # Should have at least 1 freeze event
        assert "mm_freeze_events_total 1" in body or "mm_freeze_events_total 1.0" in body
        
        conn.close()
        
    finally:
        server.stop()


def test_exec_loop_structured_logs():
    """Test that ExecutionLoop emits structured logs."""
    clock = FakeClock()
    
    # Create components
    exchange = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)
    order_store = InMemoryOrderStore()
    risk_monitor = RuntimeRiskMonitor(
        max_inventory_usd_per_symbol=10000.0,
        max_total_notional_usd=50000.0,
        edge_freeze_threshold_bps=1.5,
    )
    
    loop = ExecutionLoop(
        exchange=exchange,
        order_store=order_store,
        risk_monitor=risk_monitor,
        clock=clock,
    )
    
    # Place order (should emit log)
    quote = Quote(symbol="BTCUSDT", bid=50000.0, ask=50010.0, timestamp_ms=clock())
    params = ExecutionParams(
        symbols=["BTCUSDT"],
        iterations=1,
        max_inventory_usd_per_symbol=10000.0,
        max_total_notional_usd=50000.0,
        edge_freeze_threshold_bps=1.5,
    )
    
    loop.on_quote(quote, params)
    
    # Note: Actual log capture requires stderr redirection
    # For now, we verify that the code path is covered
    assert loop.stats["orders_placed"] > 0


def test_metrics_reflect_execution_state():
    """Test that metrics accurately reflect execution state."""
    clock = FakeClock()
    
    # Reset global metrics registry for clean test
    # (In real test, we'd use a separate registry, but for simplicity...)
    
    exchange = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)
    order_store = InMemoryOrderStore()
    risk_monitor = RuntimeRiskMonitor(
        max_inventory_usd_per_symbol=10000.0,
        max_total_notional_usd=50000.0,
        edge_freeze_threshold_bps=1.5,
    )
    
    loop = ExecutionLoop(
        exchange=exchange,
        order_store=order_store,
        risk_monitor=risk_monitor,
        clock=clock,
    )
    
    # Get initial metrics
    initial_output = metrics.render_prometheus()
    
    # Place orders
    quote = Quote(symbol="ETHUSDT", bid=3000.0, ask=3001.0, timestamp_ms=clock())
    params = ExecutionParams(
        symbols=["ETHUSDT"],
        iterations=1,
        max_inventory_usd_per_symbol=10000.0,
        max_total_notional_usd=50000.0,
        edge_freeze_threshold_bps=1.5,
    )
    
    loop.on_quote(quote, params)
    
    # Get updated metrics
    updated_output = metrics.render_prometheus()
    
    # Should have incremented orders_placed for ETHUSDT
    assert "mm_orders_placed_total" in updated_output
    assert "ETHUSDT" in updated_output


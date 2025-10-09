"""
Microbenchmark for quote loop latency.

Tests that quote loop operations complete with p95 < 5ms on mocks.
This ensures fast-cancel and taker cap checks don't add significant overhead.
"""
import pytest
import time
import statistics
from unittest.mock import Mock, AsyncMock
from src.strategy.quote_loop import QuoteLoop
from src.execution.order_manager import OrderState
from src.common.di import AppContext


@pytest.fixture
def mock_ctx():
    """Create mock AppContext with minimal config."""
    ctx = Mock(spec=AppContext)
    
    # Mock fast_cancel config
    fast_cancel_cfg = Mock()
    fast_cancel_cfg.enabled = True
    fast_cancel_cfg.cancel_threshold_bps = 3.0
    fast_cancel_cfg.cooldown_after_spike_ms = 500
    fast_cancel_cfg.spike_threshold_bps = 10.0
    
    # Mock taker_cap config
    taker_cap_cfg = Mock()
    taker_cap_cfg.enabled = True
    taker_cap_cfg.max_taker_fills_per_hour = 50
    taker_cap_cfg.max_taker_share_pct = 10.0
    taker_cap_cfg.rolling_window_sec = 3600
    
    ctx.cfg = Mock()
    ctx.cfg.fast_cancel = fast_cancel_cfg
    ctx.cfg.taker_cap = taker_cap_cfg
    
    return ctx


@pytest.fixture
def mock_order_manager():
    """Create mock OrderManager with active orders."""
    manager = Mock()
    manager.active_orders = {}
    manager.cancel_order = AsyncMock()  # Instant mock cancel
    return manager


@pytest.fixture
def quote_loop(mock_ctx, mock_order_manager):
    """Create QuoteLoop instance."""
    return QuoteLoop(mock_ctx, mock_order_manager)


def create_mock_order(client_order_id: str, symbol: str, price: float) -> OrderState:
    """Helper to create mock order."""
    return OrderState(
        client_order_id=client_order_id,
        order_id="",
        symbol=symbol,
        side="Buy",
        price=price,
        qty=0.01,
        status="New",
        create_time=time.time(),
        last_update_time=time.time()
    )


def benchmark_latency(func, iterations=1000):
    """
    Benchmark function latency.
    
    Returns:
        dict with p50, p95, p99, mean, max latencies in milliseconds
    """
    latencies = []
    
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        latencies.append((end - start) * 1000.0)  # Convert to ms
    
    latencies.sort()
    
    return {
        'p50': latencies[len(latencies) // 2],
        'p95': latencies[int(len(latencies) * 0.95)],
        'p99': latencies[int(len(latencies) * 0.99)],
        'mean': statistics.mean(latencies),
        'max': max(latencies),
        'min': min(latencies),
        'iterations': iterations,
    }


def test_should_fast_cancel_latency(quote_loop):
    """Benchmark should_fast_cancel() latency."""
    order = create_mock_order("test123", "BTCUSDT", 50000.0)
    current_mid = 50025.0  # 5 bps move
    now_ms = int(time.time() * 1000)
    
    def run_check():
        quote_loop.should_fast_cancel(order, current_mid, now_ms)
    
    results = benchmark_latency(run_check, iterations=10000)
    
    print(f"\n[BENCHMARK] should_fast_cancel():")
    print(f"  p50: {results['p50']:.4f} ms")
    print(f"  p95: {results['p95']:.4f} ms")
    print(f"  p99: {results['p99']:.4f} ms")
    print(f"  mean: {results['mean']:.4f} ms")
    print(f"  max: {results['max']:.4f} ms")
    
    # Assert p95 < 0.1ms (should be very fast, just Python arithmetic)
    assert results['p95'] < 0.1, f"p95 latency {results['p95']:.4f}ms exceeds 0.1ms target"


def test_can_place_taker_order_latency(quote_loop):
    """Benchmark can_place_taker_order() latency."""
    # Pre-populate with some fills
    for i in range(100):
        quote_loop.record_fill("BTCUSDT", is_taker=(i % 3 == 0))
    
    def run_check():
        quote_loop.can_place_taker_order("BTCUSDT")
    
    results = benchmark_latency(run_check, iterations=10000)
    
    print(f"\n[BENCHMARK] can_place_taker_order():")
    print(f"  p50: {results['p50']:.4f} ms")
    print(f"  p95: {results['p95']:.4f} ms")
    print(f"  p99: {results['p99']:.4f} ms")
    print(f"  mean: {results['mean']:.4f} ms")
    print(f"  max: {results['max']:.4f} ms")
    
    # Assert p95 < 0.5ms (involves deque iteration)
    assert results['p95'] < 0.5, f"p95 latency {results['p95']:.4f}ms exceeds 0.5ms target"


def test_record_fill_latency(quote_loop):
    """Benchmark record_fill() latency."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    def run_record():
        symbol = symbols[int(time.time() * 1000) % len(symbols)]
        quote_loop.record_fill(symbol, is_taker=(int(time.time() * 1000) % 2 == 0))
    
    results = benchmark_latency(run_record, iterations=10000)
    
    print(f"\n[BENCHMARK] record_fill():")
    print(f"  p50: {results['p50']:.4f} ms")
    print(f"  p95: {results['p95']:.4f} ms")
    print(f"  p99: {results['p99']:.4f} ms")
    print(f"  mean: {results['mean']:.4f} ms")
    print(f"  max: {results['max']:.4f} ms")
    
    # Assert p95 < 0.1ms (just appending to deque)
    assert results['p95'] < 0.1, f"p95 latency {results['p95']:.4f}ms exceeds 0.1ms target"


def test_get_taker_stats_latency(quote_loop):
    """Benchmark get_taker_stats() latency."""
    # Pre-populate with realistic fill history
    now_ms = int(time.time() * 1000)
    for i in range(500):
        quote_loop.record_fill(
            "BTCUSDT",
            is_taker=(i % 4 == 0),
            timestamp_ms=now_ms - (i * 100)  # Spread over time
        )
    
    def run_get_stats():
        quote_loop.get_taker_stats()
    
    results = benchmark_latency(run_get_stats, iterations=5000)
    
    print(f"\n[BENCHMARK] get_taker_stats():")
    print(f"  p50: {results['p50']:.4f} ms")
    print(f"  p95: {results['p95']:.4f} ms")
    print(f"  p99: {results['p99']:.4f} ms")
    print(f"  mean: {results['mean']:.4f} ms")
    print(f"  max: {results['max']:.4f} ms")
    
    # Assert p95 < 1.0ms (involves cleanup + iteration)
    assert results['p95'] < 1.0, f"p95 latency {results['p95']:.4f}ms exceeds 1.0ms target"


@pytest.mark.asyncio
async def test_check_and_cancel_stale_orders_latency(quote_loop, mock_order_manager):
    """Benchmark check_and_cancel_stale_orders() latency (with mock orders)."""
    symbol = "BTCUSDT"
    now_ms = int(time.time() * 1000)
    current_mid = 50030.0
    
    # Create 10 active orders
    for i in range(10):
        order = create_mock_order(f"order{i}", symbol, 50000.0 + (i * 10))
        mock_order_manager.active_orders[f"order{i}"] = order
    
    # Benchmark (note: this is async so we measure differently)
    latencies = []
    iterations = 1000
    
    for _ in range(iterations):
        start = time.perf_counter()
        await quote_loop.check_and_cancel_stale_orders(symbol, current_mid, now_ms)
        end = time.perf_counter()
        latencies.append((end - start) * 1000.0)
    
    latencies.sort()
    
    results = {
        'p50': latencies[len(latencies) // 2],
        'p95': latencies[int(len(latencies) * 0.95)],
        'p99': latencies[int(len(latencies) * 0.99)],
        'mean': statistics.mean(latencies),
        'max': max(latencies),
    }
    
    print(f"\n[BENCHMARK] check_and_cancel_stale_orders() [10 orders, mocked cancel]:")
    print(f"  p50: {results['p50']:.4f} ms")
    print(f"  p95: {results['p95']:.4f} ms")
    print(f"  p99: {results['p99']:.4f} ms")
    print(f"  mean: {results['mean']:.4f} ms")
    print(f"  max: {results['max']:.4f} ms")
    
    # Assert p95 < 0.5ms (with mocked cancel, should be fast)
    assert results['p95'] < 0.5, f"p95 latency {results['p95']:.4f}ms exceeds 0.5ms target"


def test_combined_hot_path_latency(quote_loop, mock_order_manager):
    """Benchmark combined hot path: fast-cancel check + taker cap check."""
    symbol = "BTCUSDT"
    now_ms = int(time.time() * 1000)
    
    # Setup: Add some orders and fills
    for i in range(5):
        order = create_mock_order(f"order{i}", symbol, 50000.0)
        mock_order_manager.active_orders[f"order{i}"] = order
    
    for i in range(50):
        quote_loop.record_fill(symbol, is_taker=(i % 5 == 0))
    
    current_mid = 50020.0
    
    def run_hot_path():
        # Fast-cancel check (all orders)
        for cid, order in mock_order_manager.active_orders.items():
            quote_loop.should_fast_cancel(order, current_mid, now_ms)
        
        # Taker cap check
        quote_loop.can_place_taker_order(symbol)
        
        # Get stats (for monitoring)
        quote_loop.get_taker_stats()
    
    results = benchmark_latency(run_hot_path, iterations=5000)
    
    print(f"\n[BENCHMARK] Combined hot path [5 orders, 50 fills]:")
    print(f"  p50: {results['p50']:.4f} ms")
    print(f"  p95: {results['p95']:.4f} ms")
    print(f"  p99: {results['p99']:.4f} ms")
    print(f"  mean: {results['mean']:.4f} ms")
    print(f"  max: {results['max']:.4f} ms")
    
    # Assert p95 < 5ms (main target from requirements)
    assert results['p95'] < 5.0, f"p95 latency {results['p95']:.4f}ms exceeds 5ms target"
    
    # Ideally should be much faster (< 2ms)
    if results['p95'] < 2.0:
        print(f"  ✓ Excellent: p95={results['p95']:.4f}ms < 2ms")
    elif results['p95'] < 5.0:
        print(f"  ✓ Good: p95={results['p95']:.4f}ms < 5ms")


def test_worst_case_latency(quote_loop, mock_order_manager):
    """Benchmark worst case: many orders, large fill history."""
    symbol = "BTCUSDT"
    now_ms = int(time.time() * 1000)
    
    # Worst case: 30 active orders, 1000 fills in history
    for i in range(30):
        order = create_mock_order(f"order{i}", symbol, 50000.0 + (i * 5))
        mock_order_manager.active_orders[f"order{i}"] = order
    
    for i in range(1000):
        quote_loop.record_fill(
            symbol,
            is_taker=(i % 3 == 0),
            timestamp_ms=now_ms - (i * 10)
        )
    
    current_mid = 50030.0
    
    def run_worst_case():
        # Check all orders for fast-cancel
        for cid, order in mock_order_manager.active_orders.items():
            quote_loop.should_fast_cancel(order, current_mid, now_ms)
        
        # Check taker cap
        quote_loop.can_place_taker_order(symbol)
        
        # Get stats
        quote_loop.get_taker_stats()
    
    results = benchmark_latency(run_worst_case, iterations=1000)
    
    print(f"\n[BENCHMARK] Worst case [30 orders, 1000 fills]:")
    print(f"  p50: {results['p50']:.4f} ms")
    print(f"  p95: {results['p95']:.4f} ms")
    print(f"  p99: {results['p99']:.4f} ms")
    print(f"  mean: {results['mean']:.4f} ms")
    print(f"  max: {results['max']:.4f} ms")
    
    # Even in worst case, should be < 10ms
    assert results['p95'] < 10.0, f"p95 latency {results['p95']:.4f}ms exceeds 10ms worst-case target"
    
    if results['p95'] < 5.0:
        print(f"  ✓ Excellent: Even worst case p95={results['p95']:.4f}ms < 5ms")


if __name__ == "__main__":
    # Run benchmarks standalone
    pytest.main([__file__, "-v", "-s"])


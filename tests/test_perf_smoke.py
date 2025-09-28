import os
import time
import json
from typing import List, Dict

import pytest
import orjson


pytestmark = pytest.mark.skipif(os.getenv("PERF") != "1", reason="perf disabled")


def test_json_vs_orjson_performance():
    # Prepare 50k small dicts
    num_items = 50_000
    data: List[Dict] = [{"a": i, "b": i * 2, "c": i % 5} for i in range(num_items)]

    # json dumps
    t0 = time.perf_counter()
    json_ser = [json.dumps(d) for d in data]
    t1 = time.perf_counter()
    json_dump_time = t1 - t0

    # json loads
    t2 = time.perf_counter()
    _ = [json.loads(s) for s in json_ser]
    t3 = time.perf_counter()
    json_load_time = t3 - t2

    # orjson dumps (bytes)
    t4 = time.perf_counter()
    orjson_ser = [orjson.dumps(d) for d in data]
    t5 = time.perf_counter()
    orjson_dump_time = t5 - t4

    # orjson loads (from bytes)
    t6 = time.perf_counter()
    _ = [orjson.loads(b) for b in orjson_ser]
    t7 = time.perf_counter()
    orjson_load_time = t7 - t6

    json_total = json_dump_time + json_load_time
    orjson_total = orjson_dump_time + orjson_load_time

    # Avoid division by zero
    eps = 1e-9
    dump_speedup = (json_dump_time + eps) / (orjson_dump_time + eps)
    load_speedup = (json_load_time + eps) / (orjson_load_time + eps)
    total_speedup = (json_total + eps) / (orjson_total + eps)

    print(
        f"orjson speedup: dumps={dump_speedup:.2f}x, loads={load_speedup:.2f}x, total={total_speedup:.2f}x"
    )


def test_numba_spread_calc_speedup():
    try:
        import numpy as np  # type: ignore
        from numba import njit  # type: ignore
    except Exception:
        pytest.skip("numba not available")

    # Simple numeric function to benchmark
    def spread_calc(arr: "np.ndarray") -> float:  # type: ignore[name-defined]
        acc = 0.0
        for i in range(arr.shape[0] - 1):
            acc += abs(arr[i + 1] - arr[i])
        return acc

    # JIT-compiled version
    jit_spread_calc = njit(cache=True, fastmath=True)(spread_calc)

    rng = np.random.default_rng(123)
    x = rng.random(200_000, dtype=np.float64)

    # Warmup compile
    _ = jit_spread_calc(x)

    # Python timing
    t0 = time.perf_counter()
    _ = spread_calc(x)
    t1 = time.perf_counter()
    py_time = t1 - t0

    # JIT timing
    t2 = time.perf_counter()
    _ = jit_spread_calc(x)
    t3 = time.perf_counter()
    jit_time = t3 - t2

    speedup = (py_time + 1e-9) / (jit_time + 1e-9)
    print(f"numba speedup: {speedup:.2f}x (python={py_time*1e3:.2f}ms, jit={jit_time*1e3:.2f}ms)")


@pytest.mark.skipif(os.getenv('PERF') != '1', reason='Performance tests disabled')
def test_strategy_quoting_performance():
    """Test quoting strategy performance under load."""
    from src.strategy.quoting import MarketMakingStrategy
    from src.common.config import Config
    
    # Create minimal config
    config = Config(
        trading={"symbols": ["BTCUSDT"], "base_spread_bps": 10.0, "ladder_levels": 3, "ladder_step_bps": 5.0, "post_only": True, "min_notional_usd": 10.0},
        risk={"max_position_usd": 1000.0, "target_inventory_usd": 0.0, "daily_max_loss_usd": 100.0, "max_cancels_per_min": 90},
        strategy={"volatility_lookback_sec": 30, "imbalance_weight": 0.4, "microprice_weight": 0.6},
        storage={"backend": "parquet", "parquet_path": "./data"}
    )
    
    strategy = MarketMakingStrategy(config)
    
    # Mock orderbook
    from src.common.models import OrderBook, PriceLevel
    from decimal import Decimal
    mock_orderbook = OrderBook(
        symbol="BTCUSDT",
        timestamp=datetime.now(timezone.utc),
        sequence=0,
        bids=[PriceLevel(price=Decimal("50000"), size=Decimal("1.0"))],
        asks=[PriceLevel(price=Decimal("50100"), size=Decimal("1.0"))]
    )
    
    start_time = time.perf_counter()
    for _ in range(10000):
        strategy._generate_quotes("BTCUSDT", mock_orderbook)
    duration = time.perf_counter() - start_time
    
    assert duration < 1.0  # Should complete in <1 second
    print(f"Strategy quoting performance: {duration*1e3:.2f}ms for 10k iterations")


@pytest.mark.skipif(os.getenv('PERF') != '1', reason='Performance tests disabled')
def test_orjson_vs_json_performance():
    """Test orjson vs built-in json performance."""
    import json
    import orjson
    
    # Create test data
    test_data = {
        "symbol": "BTCUSDT",
        "price": 50000.0,
        "qty": 1.0,
        "side": "Buy",
        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        "nested": {
            "level1": {"level2": {"level3": "deep_value"}},
            "array": [1, 2, 3, 4, 5] * 100
        }
    }
    
    # Warm up
    for _ in range(100):
        json.dumps(test_data)
        orjson.dumps(test_data)
    
    # Test json
    start_time = time.perf_counter()
    for _ in range(10000):
        json.dumps(test_data)
    json_time = time.perf_counter() - start_time
    
    # Test orjson
    start_time = time.perf_counter()
    for _ in range(10000):
        orjson.dumps(test_data)
    orjson_time = time.perf_counter() - start_time
    
    speedup = json_time / orjson_time
    print(f"orjson speedup: {speedup:.2f}x (json={json_time*1e3:.2f}ms, orjson={orjson_time*1e3:.2f}ms)")
    
    assert speedup > 2.0  # orjson should be at least 2x faster



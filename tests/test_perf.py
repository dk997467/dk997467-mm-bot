"""
Performance smoke tests (run only with PERF=1).

- Compare built-in json vs orjson
- Compare numba-accelerated volatility vs numpy baseline

These tests are marked slow and are skipped by default to avoid CI flakiness.
"""

import os
import time
import json as pyjson
from decimal import Decimal
from typing import List

import numpy as np
import pytest

# Add PERF gating
PERF_ENABLED = os.environ.get("PERF") == "1"


@pytest.mark.slow
@pytest.mark.skipif(not PERF_ENABLED, reason="Set PERF=1 to run perf smoke tests")
def test_orjson_vs_json_perf():
    try:
        import orjson
    except Exception:
        pytest.skip("orjson not available")

    # Synthetic payload
    payload = {
        "ints": list(range(1000)),
        "floats": [i * 0.123 for i in range(1000)],
        "strings": [f"sym_{i}" for i in range(1000)],
        "nested": {f"k{i}": {"a": i, "b": i * 2} for i in range(200)},
    }

    # Warmup
    _ = pyjson.dumps(payload)
    _ = orjson.dumps(payload)

    # Measure json
    iters = 200
    t0 = time.perf_counter()
    for _ in range(iters):
        s = pyjson.dumps(payload)
        _ = pyjson.loads(s)
    json_time = time.perf_counter() - t0

    # Measure orjson
    t0 = time.perf_counter()
    for _ in range(iters):
        b = orjson.dumps(payload)
        _ = orjson.loads(b)
    orjson_time = time.perf_counter() - t0

    # Functional check
    assert pyjson.loads(pyjson.dumps(payload)) == orjson.loads(orjson.dumps(payload))

    # Report
    print(f"json_time={json_time:.6f}s, orjson_time={orjson_time:.6f}s, speedup={json_time/max(orjson_time,1e-12):.2f}x")


@pytest.mark.slow
@pytest.mark.skipif(not PERF_ENABLED, reason="Set PERF=1 to run perf smoke tests")
def test_numba_volatility_perf():
    # Import utils dynamically to access calculate_volatility
    from src.common import utils

    # Generate price series
    n = 100_000
    base = 100.0
    rng = np.random.default_rng(42)
    # Simulate random walk
    returns = rng.normal(loc=0.0, scale=0.001, size=n)
    prices = base * np.exp(np.cumsum(returns))

    # Convert to Decimal list for API compatibility
    price_list: List[Decimal] = [Decimal(str(x)) for x in prices]

    # Baseline using numpy std
    def numpy_vol(prices_np: np.ndarray, lookback: int) -> float:
        if prices_np.size < 2:
            return 0.0
        tail = prices_np[: lookback + 1]
        if tail.size < 2:
            return 0.0
        rets = np.diff(tail) / tail[:-1]
        if rets.size == 0:
            return 0.0
        return float(np.std(rets))

    lookback = 1000

    # Warmup utils (compiles numba if available)
    _ = utils.calculate_volatility(price_list, lookback)

    # Measure utils (numba-backed if available)
    iters = 50
    t0 = time.perf_counter()
    for _ in range(iters):
        v1 = utils.calculate_volatility(price_list, lookback)
    utils_time = time.perf_counter() - t0

    # Measure numpy baseline
    t0 = time.perf_counter()
    for _ in range(iters):
        v2 = numpy_vol(prices, lookback)
    numpy_time = time.perf_counter() - t0

    # Validate values close
    assert abs(float(v1) - float(v2)) <= 1e-6

    print(f"vol_utils_time={utils_time:.6f}s, vol_numpy_time={numpy_time:.6f}s, ratio={numpy_time/max(utils_time,1e-12):.2f}x")

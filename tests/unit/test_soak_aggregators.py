"""
Unit tests for soak test aggregators (p95, EMA, rolling windows).
"""

import sys
sys.path.insert(0, ".")

from tools.soak.run import calculate_p95, calculate_ema


def test_calculate_p95():
    """Test P95 calculation."""
    # Empty list
    assert calculate_p95([]) == 0.0
    
    # Single value
    assert calculate_p95([100.0]) == 100.0
    
    # Multiple values
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p95 = calculate_p95(values)
    assert p95 == 100.0  # 95th percentile of 10 values at index 9 (last element)
    
    # Unsorted input (should sort internally)
    values = [100.0, 10.0, 50.0, 30.0, 70.0]
    p95 = calculate_p95(values)
    # Sorted: [10, 30, 50, 70, 100], index 4 = 100.0
    assert p95 == 100.0
    
    print("✓ P95 calculation tests passed")


def test_calculate_ema():
    """Test EMA calculation."""
    # Empty list
    assert calculate_ema([], 5) == 0.0
    
    # Single value
    assert calculate_ema([100.0], 5) == 100.0
    
    # Multiple values with half-life = 1 (alpha = 0.5)
    values = [10.0, 20.0, 30.0, 40.0]
    ema = calculate_ema(values, 1)
    # EMA with alpha=0.5: 10 → 15 → 22.5 → 31.25
    assert abs(ema - 31.25) < 0.01
    
    # Constant values
    values = [5.0, 5.0, 5.0, 5.0, 5.0]
    ema = calculate_ema(values, 3)
    assert abs(ema - 5.0) < 0.01
    
    print("✓ EMA calculation tests passed")


if __name__ == "__main__":
    test_calculate_p95()
    test_calculate_ema()
    print("\n✓ All soak aggregator tests passed")


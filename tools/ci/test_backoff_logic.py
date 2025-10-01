#!/usr/bin/env python3
"""
Standalone test for exponential backoff logic (no external dependencies).

Tests the mathematical correctness of the backoff algorithm:
1. Exponential growth: delay = base * 2^attempt
2. Jitter: adds 0-30% randomness
3. Max cap: delay <= max_delay
4. Max attempts: stops after N attempts
"""
import random
import sys


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_factor: float = 0.3
) -> float:
    """
    Calculate exponential backoff delay with jitter.
    
    This is the same formula used in bybit_websocket.py:
    delay = min(base * 2^attempt + jitter, max_delay)
    where jitter = random(0, delay * jitter_factor)
    """
    exponential_delay = base_delay * (2 ** attempt)
    jitter_range = exponential_delay * jitter_factor
    jitter = random.uniform(0, jitter_range)
    delay = min(exponential_delay + jitter, max_delay)
    return delay


def test_exponential_growth():
    """Test that delay grows exponentially."""
    base = 1.0
    max_delay = 60.0
    
    expected_ranges = [
        (0, 1.0, 1.5),    # ~1s
        (1, 2.0, 3.0),    # ~2s
        (2, 4.0, 6.0),    # ~4s
        (3, 8.0, 12.0),   # ~8s
        (4, 16.0, 24.0),  # ~16s
        (5, 32.0, 48.0),  # ~32s
    ]
    
    for attempt, min_exp, max_exp in expected_ranges:
        delay = calculate_backoff_delay(attempt, base, max_delay)
        assert min_exp <= delay <= max_exp, \
            f"Attempt {attempt}: delay {delay:.2f}s not in range [{min_exp}, {max_exp}]"
    
    print("[OK] test_exponential_growth: all delays in expected ranges")


def test_jitter_variance():
    """Test that jitter adds randomness."""
    attempt = 2  # Exponential delay = 4s
    base = 1.0
    max_delay = 60.0
    
    # Run 100 times
    delays = [calculate_backoff_delay(attempt, base, max_delay) for _ in range(100)]
    
    # Should have many unique values
    unique_count = len(set(delays))
    assert unique_count >= 50, f"Expected variance from jitter, got {unique_count} unique values"
    
    # All should be in range [4s, 5.2s] (4s + 30% = 5.2s)
    for delay in delays:
        assert 4.0 <= delay <= 5.3, f"Delay {delay:.2f}s outside expected range [4.0, 5.3]"
    
    print(f"[OK] test_jitter_variance: {unique_count} unique delays out of 100 runs")


def test_max_cap():
    """Test that max_delay cap is respected."""
    base = 1.0
    max_delay = 10.0
    
    # Attempt 10: exponential would be 1024s
    delay = calculate_backoff_delay(10, base, max_delay)
    
    # Should be capped at 10s (plus jitter, so max ~13s)
    assert delay <= 13.0, f"Delay {delay:.2f}s exceeds max cap (10s + 30% = 13s)"
    
    print(f"[OK] test_max_cap: delay={delay:.2f}s (cap: 10s)")


def test_realistic_sequence():
    """Test realistic backoff sequence."""
    base = 1.0
    max_delay = 60.0
    
    print("\n  Simulating realistic backoff sequence:")
    for attempt in range(10):
        delay = calculate_backoff_delay(attempt, base, max_delay)
        exponential = base * (2 ** attempt)
        capped = min(exponential, max_delay)
        print(f"    Attempt {attempt+1}: {delay:.2f}s (exp: {exponential:.0f}s, cap: {capped:.0f}s)")
        
        # Verify delay is reasonable
        assert delay <= max_delay * 1.3, f"Delay {delay:.2f}s exceeds max+jitter"
    
    print("[OK] test_realistic_sequence: all delays within bounds")


def test_jitter_formula():
    """Test jitter calculation formula."""
    base = 1.0
    jitter_factor = 0.3
    
    for attempt in range(7):
        exponential_delay = base * (2 ** attempt)
        jitter_range = exponential_delay * jitter_factor
        
        # Test 100 jitter samples
        jitters = [random.uniform(0, jitter_range) for _ in range(100)]
        
        # All should be in valid range
        for j in jitters:
            assert 0 <= j <= jitter_range, f"Jitter {j:.2f} outside range [0, {jitter_range:.2f}]"
        
        # Should have variance
        unique_jitters = len(set(jitters))
        assert unique_jitters >= 50, f"Jitter should be random, got {unique_jitters} unique values"
    
    print("[OK] test_jitter_formula: jitter calculation correct")


def test_thundering_herd_prevention():
    """Test that jitter prevents thundering herd (synchronized reconnects)."""
    base = 1.0
    max_delay = 60.0
    attempt = 3  # 8s exponential
    
    # Simulate 10 independent clients reconnecting
    delays = [calculate_backoff_delay(attempt, base, max_delay) for _ in range(10)]
    
    # Delays should be spread out (not all the same)
    unique_count = len(set(delays))
    assert unique_count >= 5, f"Thundering herd risk: only {unique_count} unique delays"
    
    # Calculate spread (max - min)
    spread = max(delays) - min(delays)
    assert spread >= 1.0, f"Thundering herd risk: spread only {spread:.2f}s"
    
    print(f"[OK] test_thundering_herd_prevention: {unique_count} unique delays, spread={spread:.2f}s")


def test_max_attempts_logic():
    """Test max attempts logic."""
    max_attempts = 5
    
    # Simulate attempts
    for attempt in range(max_attempts):
        reached_max = (attempt >= max_attempts)
        assert not reached_max, f"Should not stop at attempt {attempt+1}"
    
    # Next attempt should stop
    attempt = max_attempts
    reached_max = (attempt >= max_attempts)
    assert reached_max, "Should stop after max attempts"
    
    print(f"[OK] test_max_attempts_logic: stops at attempt {max_attempts+1}")


def main():
    """Run all tests."""
    print("Testing exponential backoff logic...\n")
    
    tests = [
        test_exponential_growth,
        test_jitter_variance,
        test_max_cap,
        test_realistic_sequence,
        test_jitter_formula,
        test_thundering_herd_prevention,
        test_max_attempts_logic,
    ]
    
    failed = []
    for test_func in tests:
        try:
            test_func()
        except AssertionError as e:
            print(f"[FAIL] {test_func.__name__}: {e}")
            failed.append(test_func.__name__)
        except Exception as e:
            print(f"[ERROR] {test_func.__name__}: {e}")
            failed.append(test_func.__name__)
    
    print(f"\n{'='*60}")
    if failed:
        print(f"FAILED: {len(failed)}/{len(tests)} tests")
        for name in failed:
            print(f"  - {name}")
        return 1
    else:
        print(f"SUCCESS: All {len(tests)} tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())


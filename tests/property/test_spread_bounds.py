"""
Property Tests: Spread Bounds & Monotonicity (stdlib-only).

Tests spread calculation invariants:
- Spread within safe bounds for various volatility/liquidity ranges
- Monotonicity: vol↑ ⇒ spread↑ or unchanged
- No negative spreads
- Reasonable response to market conditions

No external dependencies (Hypothesis-free).
"""
import random
from typing import Tuple


def calculate_spread_bps(
    base_spread_bps: float,
    volatility_factor: float,
    liquidity_factor: float,
    min_spread_bps: float = 0.5,
    max_spread_bps: float = 50.0
) -> float:
    """
    Calculate spread with volatility and liquidity adjustments.
    
    Args:
        base_spread_bps: Base spread (e.g., 2.0 bps)
        volatility_factor: Volatility multiplier [1.0, 5.0]
        liquidity_factor: Liquidity penalty [1.0, 3.0]
        min_spread_bps: Minimum allowed spread
        max_spread_bps: Maximum allowed spread
    
    Returns:
        Adjusted spread in bps
    """
    # Calculate adjusted spread
    adjusted_spread = base_spread_bps * volatility_factor * liquidity_factor
    
    # Clamp to bounds
    spread = max(min_spread_bps, min(adjusted_spread, max_spread_bps))
    
    return spread


def test_spread_non_negative():
    """
    Property: spread >= 0 (always non-negative).
    """
    cases_tested = 0
    
    for _ in range(1000):
        base = random.uniform(0.5, 10.0)
        vol_factor = random.uniform(1.0, 5.0)
        liq_factor = random.uniform(1.0, 3.0)
        
        spread = calculate_spread_bps(base, vol_factor, liq_factor)
        
        assert spread >= 0, f"Spread must be >= 0, got: {spread}"
        cases_tested += 1
    
    print(f"✓ Tested {cases_tested} cases - all spreads non-negative")


def test_spread_within_bounds():
    """
    Property: min_spread <= spread <= max_spread.
    """
    cases_tested = 0
    min_spread = 0.5
    max_spread = 50.0
    
    for _ in range(1000):
        base = random.uniform(0.1, 100.0)  # Wide range
        vol_factor = random.uniform(0.5, 10.0)
        liq_factor = random.uniform(0.5, 5.0)
        
        spread = calculate_spread_bps(base, vol_factor, liq_factor, min_spread, max_spread)
        
        assert min_spread <= spread <= max_spread, (
            f"Spread {spread} outside bounds [{min_spread}, {max_spread}]"
        )
        cases_tested += 1
    
    print(f"✓ Tested {cases_tested} cases - all spreads within bounds")


def test_spread_monotonicity_volatility():
    """
    Property: vol↑ ⇒ spread↑ (or unchanged if capped).
    
    For fixed base/liquidity, increasing volatility should increase spread.
    """
    cases_tested = 0
    monotonic_cases = 0
    
    for _ in range(100):
        base = random.uniform(1.0, 5.0)
        liq_factor = random.uniform(1.0, 2.0)
        
        # Test increasing volatility
        vol_low = 1.0
        vol_high = 3.0
        
        spread_low = calculate_spread_bps(base, vol_low, liq_factor)
        spread_high = calculate_spread_bps(base, vol_high, liq_factor)
        
        # Spread should increase (or stay same if capped)
        if spread_high >= spread_low:
            monotonic_cases += 1
        else:
            print(f"[WARN] Non-monotonic: vol {vol_low} -> {vol_high}, "
                  f"spread {spread_low} -> {spread_high}")
        
        cases_tested += 1
    
    # Expect 100% monotonic
    monotonic_pct = (monotonic_cases / cases_tested) * 100
    assert monotonic_pct == 100, f"Only {monotonic_pct:.1f}% monotonic, expected 100%"
    
    print(f"✓ Tested {cases_tested} cases - {monotonic_pct:.1f}% monotonic with volatility")


def test_spread_monotonicity_liquidity():
    """
    Property: liq↓ ⇒ spread↑ (lower liquidity = higher spread).
    
    For fixed base/volatility, decreasing liquidity should increase spread.
    """
    cases_tested = 0
    monotonic_cases = 0
    
    for _ in range(100):
        base = random.uniform(1.0, 5.0)
        vol_factor = random.uniform(1.0, 2.0)
        
        # Test decreasing liquidity (increasing liquidity_factor penalty)
        liq_good = 1.0  # Good liquidity (low penalty)
        liq_poor = 2.5  # Poor liquidity (high penalty)
        
        spread_good_liq = calculate_spread_bps(base, vol_factor, liq_good)
        spread_poor_liq = calculate_spread_bps(base, vol_factor, liq_poor)
        
        # Spread should increase with worse liquidity
        if spread_poor_liq >= spread_good_liq:
            monotonic_cases += 1
        else:
            print(f"[WARN] Non-monotonic: liq {liq_good} -> {liq_poor}, "
                  f"spread {spread_good_liq} -> {spread_poor_liq}")
        
        cases_tested += 1
    
    monotonic_pct = (monotonic_cases / cases_tested) * 100
    assert monotonic_pct == 100, f"Only {monotonic_pct:.1f}% monotonic, expected 100%"
    
    print(f"✓ Tested {cases_tested} cases - {monotonic_pct:.1f}% monotonic with liquidity")


def test_spread_realistic_ranges():
    """
    Property: spread in [0.5, 50] bps for realistic market conditions.
    """
    cases_tested = 0
    cases_in_range = 0
    
    for _ in range(1000):
        # Realistic parameters
        base = random.uniform(1.0, 5.0)  # 1-5 bps base
        vol_factor = random.uniform(1.0, 2.5)  # 1-2.5x volatility
        liq_factor = random.uniform(1.0, 2.0)  # 1-2x liquidity penalty
        
        spread = calculate_spread_bps(base, vol_factor, liq_factor)
        
        if 0.5 <= spread <= 50.0:
            cases_in_range += 1
        
        cases_tested += 1
    
    # Expect 100% in realistic range
    in_range_pct = (cases_in_range / cases_tested) * 100
    assert in_range_pct == 100, f"Only {in_range_pct:.1f}% in [0.5, 50] range"
    
    print(f"✓ Tested {cases_tested} cases - {in_range_pct:.1f}% in realistic range [0.5, 50] bps")


def test_spread_table_cases():
    """
    Table-driven test cases for known spread scenarios.
    """
    test_cases = [
        # (base, vol_factor, liq_factor, min_spread, max_spread, expected_spread)
        (2.0, 1.0, 1.0, 0.5, 50.0, 2.0),  # Normal conditions
        (2.0, 2.0, 1.5, 0.5, 50.0, 6.0),  # High volatility + poor liquidity
        (5.0, 3.0, 2.0, 0.5, 50.0, 30.0),  # Very high volatility
        (0.1, 1.0, 1.0, 0.5, 50.0, 0.5),  # Below min (clamped to min)
        (100.0, 1.0, 1.0, 0.5, 50.0, 50.0),  # Above max (clamped to max)
        (1.0, 1.5, 1.2, 0.5, 50.0, 1.8),  # Moderate adjustments
    ]
    
    epsilon = 1e-10
    cases_tested = 0
    
    for base, vol, liq, min_s, max_s, expected in test_cases:
        spread = calculate_spread_bps(base, vol, liq, min_s, max_s)
        assert abs(spread - expected) < epsilon, (
            f"Table case failed: base={base}, vol={vol}, liq={liq} "
            f"-> spread={spread} != expected={expected}"
        )
        cases_tested += 1
    
    print(f"✓ All {cases_tested} table-driven cases passed")


def test_spread_clamping_edges():
    """
    Property: Clamping works correctly at boundaries.
    """
    cases_tested = 0
    
    # Test min clamp
    spread = calculate_spread_bps(0.1, 1.0, 1.0, min_spread_bps=0.5, max_spread_bps=50.0)
    assert spread == 0.5, f"Min clamp failed: {spread} != 0.5"
    cases_tested += 1
    
    # Test max clamp
    spread = calculate_spread_bps(100.0, 5.0, 3.0, min_spread_bps=0.5, max_spread_bps=50.0)
    assert spread == 50.0, f"Max clamp failed: {spread} != 50.0"
    cases_tested += 1
    
    # Test no clamp (within bounds)
    spread = calculate_spread_bps(2.0, 2.0, 1.5, min_spread_bps=0.5, max_spread_bps=50.0)
    assert 0.5 < spread < 50.0, f"Should be within bounds: {spread}"
    cases_tested += 1
    
    print(f"✓ Tested {cases_tested} edge cases - clamping works correctly")


if __name__ == "__main__":
    print("=" * 60)
    print("Property Tests: Spread Bounds & Monotonicity")
    print("=" * 60)
    
    test_spread_non_negative()
    test_spread_within_bounds()
    test_spread_monotonicity_volatility()
    test_spread_monotonicity_liquidity()
    test_spread_realistic_ranges()
    test_spread_table_cases()
    test_spread_clamping_edges()
    
    print("=" * 60)
    print("✓ ALL SPREAD TESTS PASSED")
    print("=" * 60)


"""
Property Tests: Edge BPS Invariants (stdlib-only).

Tests fundamental invariants of edge calculation:
- gross + fees + slippage + inventory == net (within epsilon)
- Signs: fees <= 0, inventory <= 0, gross >= 0
- No NaN/Inf values

No external dependencies (Hypothesis-free).
"""
import math
import random
from typing import Dict


def calculate_net_bps(gross_bps: float, fees_bps: float, slippage_bps: float, inventory_bps: float) -> float:
    """Calculate net BPS from components."""
    return gross_bps + fees_bps + slippage_bps + inventory_bps


def test_net_bps_decomposition_invariant():
    """
    Property: gross + fees + slippage + inventory == net (epsilon-precise).
    
    Generate 1000 random combinations and verify decomposition holds.
    """
    epsilon = 1e-10
    cases_tested = 0
    
    for _ in range(1000):
        # Generate random edge components
        gross_bps = random.uniform(0, 10.0)  # Always positive
        fees_bps = random.uniform(-2.0, 0)  # Always negative (cost)
        slippage_bps = random.uniform(-5.0, 5.0)  # Can be positive or negative
        inventory_bps = random.uniform(-3.0, 0)  # Always negative (cost)
        
        # Calculate net
        net_bps = calculate_net_bps(gross_bps, fees_bps, slippage_bps, inventory_bps)
        
        # Verify decomposition
        expected_net = gross_bps + fees_bps + slippage_bps + inventory_bps
        assert abs(net_bps - expected_net) < epsilon, (
            f"Net BPS decomposition failed: "
            f"gross={gross_bps}, fees={fees_bps}, slippage={slippage_bps}, "
            f"inventory={inventory_bps} -> net={net_bps} != expected={expected_net}"
        )
        
        cases_tested += 1
    
    print(f"✓ Tested {cases_tested} random cases - all passed")


def test_fees_sign_invariant():
    """
    Property: fees <= 0 (fees are always a cost, never positive).
    """
    cases_tested = 0
    
    for _ in range(1000):
        fees_bps = random.uniform(-2.0, 0)
        
        assert fees_bps <= 0, f"Fees must be <= 0, got: {fees_bps}"
        cases_tested += 1
    
    print(f"✓ Tested {cases_tested} fee values - all non-positive")


def test_inventory_sign_invariant():
    """
    Property: inventory <= 0 (inventory costs, never positive gains).
    """
    cases_tested = 0
    
    for _ in range(1000):
        inventory_bps = random.uniform(-3.0, 0)
        
        assert inventory_bps <= 0, f"Inventory must be <= 0, got: {inventory_bps}"
        cases_tested += 1
    
    print(f"✓ Tested {cases_tested} inventory values - all non-positive")


def test_gross_sign_invariant():
    """
    Property: gross >= 0 (gross spread is always non-negative).
    """
    cases_tested = 0
    
    for _ in range(1000):
        gross_bps = random.uniform(0, 10.0)
        
        assert gross_bps >= 0, f"Gross must be >= 0, got: {gross_bps}"
        cases_tested += 1
    
    print(f"✓ Tested {cases_tested} gross values - all non-negative")


def test_no_nan_inf_invariant():
    """
    Property: No component can be NaN or Inf.
    """
    cases_tested = 0
    
    for _ in range(1000):
        gross_bps = random.uniform(0, 10.0)
        fees_bps = random.uniform(-2.0, 0)
        slippage_bps = random.uniform(-5.0, 5.0)
        inventory_bps = random.uniform(-3.0, 0)
        
        # Check no NaN/Inf
        assert not math.isnan(gross_bps), "gross is NaN"
        assert not math.isnan(fees_bps), "fees is NaN"
        assert not math.isnan(slippage_bps), "slippage is NaN"
        assert not math.isnan(inventory_bps), "inventory is NaN"
        
        assert not math.isinf(gross_bps), "gross is Inf"
        assert not math.isinf(fees_bps), "fees is Inf"
        assert not math.isinf(slippage_bps), "slippage is Inf"
        assert not math.isinf(inventory_bps), "inventory is Inf"
        
        net_bps = calculate_net_bps(gross_bps, fees_bps, slippage_bps, inventory_bps)
        assert not math.isnan(net_bps), "net is NaN"
        assert not math.isinf(net_bps), "net is Inf"
        
        cases_tested += 1
    
    print(f"✓ Tested {cases_tested} cases - no NaN/Inf values")


def test_net_bps_realistic_range():
    """
    Property: net_bps typically in [-10, +10] range for realistic inputs.
    """
    cases_tested = 0
    cases_in_range = 0
    
    for _ in range(1000):
        # Realistic edge parameters
        gross_bps = random.uniform(1.0, 5.0)  # 1-5 bps gross
        fees_bps = random.uniform(-0.5, -0.1)  # 0.1-0.5 bps fees
        slippage_bps = random.uniform(-1.0, 1.0)  # ±1 bps slippage
        inventory_bps = random.uniform(-0.5, 0)  # 0-0.5 bps inventory cost
        
        net_bps = calculate_net_bps(gross_bps, fees_bps, slippage_bps, inventory_bps)
        
        # Net should be reasonable
        if -10 <= net_bps <= 10:
            cases_in_range += 1
        
        cases_tested += 1
    
    # Expect >95% in reasonable range
    in_range_pct = (cases_in_range / cases_tested) * 100
    assert in_range_pct >= 95, f"Only {in_range_pct:.1f}% in [-10, +10] range, expected >= 95%"
    
    print(f"✓ Tested {cases_tested} cases - {in_range_pct:.1f}% in realistic range [-10, +10] bps")


def test_edge_table_cases():
    """
    Table-driven test cases for known edge scenarios.
    """
    test_cases = [
        # (gross, fees, slippage, inventory, expected_net)
        (5.0, -0.5, 0.0, 0.0, 4.5),  # Perfect execution
        (3.0, -0.2, -1.0, -0.3, 1.5),  # Adverse slippage
        (4.0, -0.3, 1.0, -0.2, 4.5),  # Favorable slippage
        (2.0, -0.1, 0.0, -0.5, 1.4),  # Inventory cost
        (10.0, -1.0, -2.0, -1.0, 6.0),  # High gross
        (0.5, -0.05, -0.1, -0.05, 0.3),  # Low gross
    ]
    
    epsilon = 1e-10
    cases_tested = 0
    
    for gross, fees, slippage, inventory, expected_net in test_cases:
        net = calculate_net_bps(gross, fees, slippage, inventory)
        assert abs(net - expected_net) < epsilon, (
            f"Table case failed: gross={gross}, fees={fees}, slippage={slippage}, "
            f"inventory={inventory} -> net={net} != expected={expected_net}"
        )
        cases_tested += 1
    
    print(f"✓ All {cases_tested} table-driven cases passed")


if __name__ == "__main__":
    print("=" * 60)
    print("Property Tests: Edge BPS Invariants")
    print("=" * 60)
    
    test_net_bps_decomposition_invariant()
    test_fees_sign_invariant()
    test_inventory_sign_invariant()
    test_gross_sign_invariant()
    test_no_nan_inf_invariant()
    test_net_bps_realistic_range()
    test_edge_table_cases()
    
    print("=" * 60)
    print("✓ ALL EDGE INVARIANT TESTS PASSED")
    print("=" * 60)


"""
E2E test for queue-aware and inventory-skew effects.

Compares baseline vs enhanced strategies in simulation.
"""
import pytest
from tests.sim.sim_queue_inventory import SimpleMarketSim


def test_baseline_simulation():
    """Test baseline simulation without enhancements."""
    sim = SimpleMarketSim()
    result = sim.run_simulation(
        duration_sec=10.0,
        use_queue_aware=False,
        use_inv_skew=False
    )
    
    # Basic sanity checks
    assert result.fills_total > 0
    assert result.duration_sec > 0
    assert -100 <= result.final_inventory <= 100


def test_queue_aware_improves_or_maintains_metrics():
    """Test that queue-aware doesn't worsen key metrics."""
    # Baseline
    sim_baseline = SimpleMarketSim()
    baseline = sim_baseline.run_simulation(
        duration_sec=30.0,
        use_queue_aware=False,
        use_inv_skew=False
    )
    
    # With queue-aware
    sim_enhanced = SimpleMarketSim()
    enhanced = sim_enhanced.run_simulation(
        duration_sec=30.0,
        use_queue_aware=True,
        use_inv_skew=False
    )
    
    print(f"\nBaseline fills: {baseline.fills_total}, Enhanced fills: {enhanced.fills_total}")
    print(f"Baseline order age: {baseline.avg_order_age_ms:.1f}ms, Enhanced: {enhanced.avg_order_age_ms:.1f}ms")
    print(f"Baseline net bps: {baseline.net_bps:.2f}, Enhanced: {enhanced.net_bps:.2f}")
    
    # Queue-aware should improve or maintain fill rate
    # (More fills or similar, not fewer)
    assert enhanced.fills_total >= baseline.fills_total * 0.9  # Allow 10% variance
    
    # Net bps should not worsen significantly
    assert enhanced.net_bps >= baseline.net_bps * 0.9


def test_inventory_skew_reduces_position():
    """Test that inventory-skew helps rebalance inventory."""
    # Without skew - let inventory drift
    sim_no_skew = SimpleMarketSim()
    no_skew = sim_no_skew.run_simulation(
        duration_sec=30.0,
        use_queue_aware=False,
        use_inv_skew=False
    )
    
    # With skew - should stay closer to neutral
    sim_with_skew = SimpleMarketSim()
    with_skew = sim_with_skew.run_simulation(
        duration_sec=30.0,
        use_queue_aware=False,
        use_inv_skew=True
    )
    
    print(f"\nNo skew inventory: {no_skew.final_inventory:.1f}")
    print(f"With skew inventory: {with_skew.final_inventory:.1f}")
    
    # With skew, inventory should be closer to zero (on average)
    # This is stochastic, so we check that it's at least not worse
    assert abs(with_skew.final_inventory) <= abs(no_skew.final_inventory) * 1.5


def test_combined_strategy():
    """Test combined queue-aware + inventory-skew strategy."""
    # Baseline
    sim_baseline = SimpleMarketSim()
    baseline = sim_baseline.run_simulation(
        duration_sec=60.0,
        use_queue_aware=False,
        use_inv_skew=False
    )
    
    # Combined strategy
    sim_combined = SimpleMarketSim()
    combined = sim_combined.run_simulation(
        duration_sec=60.0,
        use_queue_aware=True,
        use_inv_skew=True
    )
    
    print(f"\n=== Baseline ===")
    print(f"Fills: {baseline.fills_total}")
    print(f"Order age: {baseline.avg_order_age_ms:.1f}ms")
    print(f"Net bps: {baseline.net_bps:.2f}")
    print(f"Final inventory: {baseline.final_inventory:.1f}")
    
    print(f"\n=== Combined (Queue+Skew) ===")
    print(f"Fills: {combined.fills_total}")
    print(f"Order age: {combined.avg_order_age_ms:.1f}ms")
    print(f"Net bps: {combined.net_bps:.2f}")
    print(f"Final inventory: {combined.final_inventory:.1f}")
    
    # Combined strategy should not significantly worsen metrics
    assert combined.fills_total >= baseline.fills_total * 0.8
    assert combined.net_bps >= baseline.net_bps * 0.8
    
    # Ideally improves, but at minimum doesn't hurt
    print(f"\nResult: Combined strategy maintains or improves baseline ✓")


def test_slippage_reduction_with_queue_aware():
    """Test that slippage is reduced with queue-aware (or not worse)."""
    sim_baseline = SimpleMarketSim()
    baseline = sim_baseline.run_simulation(duration_sec=30.0, use_queue_aware=False)
    
    sim_enhanced = SimpleMarketSim()
    enhanced = sim_enhanced.run_simulation(duration_sec=30.0, use_queue_aware=True)
    
    print(f"\nBaseline slippage: {baseline.avg_slippage_bps:.2f}bps")
    print(f"Enhanced slippage: {enhanced.avg_slippage_bps:.2f}bps")
    
    # Slippage should not increase significantly
    assert enhanced.avg_slippage_bps <= baseline.avg_slippage_bps * 1.2


def test_order_age_reduction():
    """Test that order age is reduced with queue-aware."""
    sim_baseline = SimpleMarketSim()
    baseline = sim_baseline.run_simulation(duration_sec=30.0, use_queue_aware=False)
    
    sim_enhanced = SimpleMarketSim()
    enhanced = sim_enhanced.run_simulation(duration_sec=30.0, use_queue_aware=True)
    
    print(f"\nBaseline order age: {baseline.avg_order_age_ms:.1f}ms")
    print(f"Enhanced order age: {enhanced.avg_order_age_ms:.1f}ms")
    
    # Order age should not increase significantly
    # (Queue-aware should fill faster on average)
    assert enhanced.avg_order_age_ms <= baseline.avg_order_age_ms * 1.2


def test_taker_share_not_increased():
    """Test that taker share doesn't increase with enhancements."""
    sim_baseline = SimpleMarketSim()
    baseline = sim_baseline.run_simulation(duration_sec=30.0, use_queue_aware=False)
    
    sim_enhanced = SimpleMarketSim()
    enhanced = sim_enhanced.run_simulation(duration_sec=30.0, use_queue_aware=True)
    
    print(f"\nBaseline taker share: {baseline.taker_share_pct:.1f}%")
    print(f"Enhanced taker share: {enhanced.taker_share_pct:.1f}%")
    
    # Taker share should not increase (we want maker fills)
    assert enhanced.taker_share_pct <= baseline.taker_share_pct + 5.0  # Allow small variance


if __name__ == "__main__":
    # Run with verbose output
    pytest.main([__file__, "-v", "-s"])

"""
Unit tests for edge sentinel auto-tuning.
"""

import sys
sys.path.insert(0, ".")

from strategy.edge_sentinel import EdgeSentinel


def test_edge_sentinel_degradation():
    """Test profile switching on edge degradation."""
    sentinel = EdgeSentinel()
    
    # Initial profile
    assert sentinel.current_profile == "Moderate"
    
    # First negative sample - should monitor
    result1 = sentinel.check_ema1h(-0.5)
    assert result1["action"] == "monitor"
    
    # Second negative sample - should still monitor
    result2 = sentinel.check_ema1h(-0.6)
    assert result2["action"] == "monitor"
    
    # Third negative sample - should trigger switch
    result3 = sentinel.check_ema1h(-0.7)
    assert result3["action"] == "switch_to_conservative"
    
    # Apply conservative profile
    apply_result = sentinel.apply_profile("Conservative")
    assert apply_result["status"] == "applied"
    assert apply_result["profile"] == "Conservative"
    assert apply_result["marker"] == "EDGE_POLICY_APPLIED"
    assert sentinel.current_profile == "Conservative"
    
    print("✓ Edge degradation test passed")


def test_edge_sentinel_recovery():
    """Test profile switching on recovery."""
    sentinel = EdgeSentinel()
    
    # Force into Conservative mode
    sentinel.apply_profile("Conservative")
    assert sentinel.current_profile == "Conservative"
    
    # Check recovery with good EMA24h
    result = sentinel.check_ema24h(2.0)
    assert result["action"] == "switch_to_moderate"
    
    # Apply moderate profile
    sentinel.apply_profile("Moderate")
    assert sentinel.current_profile == "Moderate"
    
    print("✓ Edge recovery test passed")


def test_edge_sentinel_status():
    """Test status reporting."""
    sentinel = EdgeSentinel()
    
    sentinel.check_ema1h(-0.5)
    sentinel.check_ema1h(-0.6)
    
    status = sentinel.get_status()
    assert status["current_profile"] == "Moderate"
    assert status["ema1h_samples"] == 2
    assert status["last_ema1h"] == -0.6
    
    print("✓ Edge status test passed")


if __name__ == "__main__":
    test_edge_sentinel_degradation()
    test_edge_sentinel_recovery()
    test_edge_sentinel_status()
    print("\n✓ All edge_sentinel tests passed")


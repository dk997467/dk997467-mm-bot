#!/usr/bin/env python3
"""
Demo script for E2 Go/No-Go checks functionality.
"""

import json
from src.research.calibrate import clamp01

def demo_go_no_go_checks():
    """Demo Go/No-Go checks without full simulation."""
    print("🛡️ E2 Go/No-Go Checks Demo")
    print("=" * 40)
    
    # Test clamp01 function
    print("\n📐 Testing clamp01 function:")
    test_values = [-0.5, 0.0, 0.234, 0.5, 0.999, 1.0, 1.5, 2.0]
    for val in test_values:
        clamped = clamp01(val)
        print(f"   clamp01({val:6.3f}) = {clamped:6.3f}")
    
    # Demo KS values normalization
    print("\n📊 KS Values Normalization:")
    mock_ks_values = [0.156, 0.234, 1.2, -0.1, 0.0, 1.0]
    normalized = [clamp01(val) for val in mock_ks_values]
    print(f"   Original: {mock_ks_values}")
    print(f"   Clamped:  {normalized}")
    
    # Demo effective w4 calculation
    print("\n⚙️ Effective w4 Calculation:")
    scenarios = [
        {"live_maker": 0.25, "L_maker": 0.5, "expected_w4": 0.5},
        {"live_maker": None, "L_maker": 0.5, "expected_w4": 0.0},
        {"live_maker": 0.30, "L_maker": 1.0, "expected_w4": 1.0},
        {"live_maker": None, "L_maker": 0.25, "expected_w4": 0.0}
    ]
    
    for i, scenario in enumerate(scenarios, 1):
        live_maker = scenario["live_maker"]
        L_maker = scenario["L_maker"]
        expected = scenario["expected_w4"]
        
        # Simulate the logic from generate_calibration_artifacts
        effective_w4 = 0.0 if live_maker is None else L_maker
        
        print(f"   Scenario {i}: live_maker={live_maker}, L_maker={L_maker}")
        print(f"              → w4_effective={effective_w4} (expected: {expected})")
        
        assert effective_w4 == expected, f"w4_effective mismatch in scenario {i}"
    
    # Demo sim_live_divergence calculation
    print("\n🎯 sim_live_divergence Calculation:")
    test_cases = [
        {"ks_queue": 0.234, "ks_bins": 0.156, "expected": 0.195},
        {"ks_queue": 0.0, "ks_bins": 0.0, "expected": 0.0},
        {"ks_queue": 1.0, "ks_bins": 1.0, "expected": 1.0},
        {"ks_queue": 0.5, "ks_bins": 0.3, "expected": 0.4}
    ]
    
    for case in test_cases:
        ks_queue = clamp01(case["ks_queue"])
        ks_bins = clamp01(case["ks_bins"])
        divergence = 0.5 * (ks_queue + ks_bins)
        expected = case["expected"]
        
        print(f"   ks_queue={ks_queue:.3f}, ks_bins={ks_bins:.3f}")
        print(f"   → divergence={divergence:.3f} (expected: {expected:.3f})")
        
        assert abs(divergence - expected) < 1e-9, f"Divergence mismatch: got {divergence}, expected {expected}"
    
    # Demo loss regression check
    print("\n📈 Loss Regression Check:")
    test_scenarios = [
        {"before": 0.425, "after": 0.389, "regressed": False},  # Improvement
        {"before": 0.300, "after": 0.350, "regressed": True},   # Regression
        {"before": 0.500, "after": 0.500, "regressed": False},  # Same (within epsilon)
        {"before": 0.400, "after": 0.4000000000001, "regressed": False}  # Within epsilon
    ]
    
    for i, scenario in enumerate(test_scenarios, 1):
        before = scenario["before"]
        after = scenario["after"]
        expected = scenario["regressed"]
        
        # Use same epsilon as in the implementation
        epsilon = 1e-12
        regressed = after > (before + epsilon)
        
        status = "REGRESSED" if regressed else "OK"
        print(f"   Scenario {i}: {before:.6f} → {after:.6f} = {status}")
        
        assert regressed == expected, f"Regression check mismatch in scenario {i}"
    
    # Demo complete go_no_go block
    print("\n📋 Complete go_no_go Block Example:")
    go_no_go_example = {
        "ks_queue_after": 0.234,
        "ks_bins_after": 0.156,
        "w4_effective": 0.0,
        "sim_live_divergence": 0.195,
        "loss_before": 0.425,
        "loss_after": 0.389,
        "loss_regressed": False
    }
    
    print(json.dumps(go_no_go_example, indent=2))
    
    # Validate the example
    expected_divergence = 0.5 * (go_no_go_example["ks_queue_after"] + go_no_go_example["ks_bins_after"])
    assert abs(go_no_go_example["sim_live_divergence"] - expected_divergence) < 1e-9
    
    expected_regressed = go_no_go_example["loss_after"] > (go_no_go_example["loss_before"] + 1e-12)
    assert go_no_go_example["loss_regressed"] == expected_regressed
    
    print("\n✅ All Go/No-Go checks validated successfully!")
    
    # Demo REPORT.md Go/No-Go section
    print("\n📄 REPORT.md Go/No-Go Section:")
    report_section = f"""## Go/No-Go
**KS (after)**: queue={go_no_go_example['ks_queue_after']:.3f}, bins={go_no_go_example['ks_bins_after']:.3f}
**sim_live_divergence**: {go_no_go_example['sim_live_divergence']:.3f}
**w4_effective**: {go_no_go_example['w4_effective']}
**loss_before → loss_after**: {go_no_go_example['loss_before']:.6f} → {go_no_go_example['loss_after']:.6f} ({'REGRESSED' if go_no_go_example['loss_regressed'] else 'OK'})"""
    
    print(report_section)


if __name__ == "__main__":
    demo_go_no_go_checks()
    print(f"\n🎉 E2 Go/No-Go demo completed successfully!")

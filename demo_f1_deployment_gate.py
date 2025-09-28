#!/usr/bin/env python3
"""
Demo F1 deployment gate with D2 + E2 integration.
"""

import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from src.deploy.gate import evaluate, build_cfg_patch, make_canary_patch
from src.deploy.thresholds import GateThresholds


def create_mock_d2_report(hit_rate=0.25, maker_share=0.95, sim_live_divergence=None):
    """Create mock D2 walk-forward report."""
    return {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "symbol": "BTCUSDT"
        },
        "champion": {
            "parameters": {
                "k_vola_spread": 1.5,
                "skew_coeff": 0.1,
                "levels_per_side": 4,
                "level_spacing_coeff": 1.2,
                "min_time_in_book_ms": 1000,
                "replace_threshold_bps": 2.0,
                "imbalance_cutoff": 0.8,
                "non_whitelisted_param": 999.0
            },
            "aggregates": {
                "hit_rate_mean": hit_rate,
                "maker_share_mean": maker_share,
                "net_pnl_mean_usd": 75.0,
                "cvar95_mean_usd": -8.0,
                "win_ratio": 0.65
            }
        },
        "baseline_drift_pct": {
            "k_vola_spread": 12.0,
            "skew_coeff": -5.0,
            "levels_per_side": 0.0,
            "non_whitelisted": 200.0  # Should be ignored
        }
    }


def create_mock_e2_report(sim_live_divergence=0.1):
    """Create mock E2 calibration report."""
    return {
        "metadata": {
            "symbol": "BTCUSDT",
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        },
        "go_no_go": {
            "ks_queue_after": 0.15,
            "ks_bins_after": 0.05,
            "w4_effective": 0.0,
            "sim_live_divergence": sim_live_divergence,
            "loss_before": 0.5,
            "loss_after": 0.4,
            "loss_regressed": False
        }
    }


def demo_gate_evaluation():
    """Demo gate evaluation with different scenarios."""
    print("F1 Deployment Gate Demo")
    print("=" * 40)
    
    thresholds = GateThresholds()
    print(f"Using thresholds: max_sim_live_divergence={thresholds.max_sim_live_divergence}")
    
    # Scenario 1: All gates pass
    print("\n1. Testing PASS scenario:")
    d2_report = create_mock_d2_report(hit_rate=0.25, maker_share=0.95)
    e2_report = create_mock_e2_report(sim_live_divergence=0.1)
    
    ok, reasons, metrics = evaluate(d2_report, thresholds, None, e2_report)
    
    print(f"   Result: {'PASS' if ok else 'FAIL'}")
    print(f"   Hit rate: {metrics['hit_rate_mean']:.4f}")
    print(f"   Maker share: {metrics['maker_share_mean']:.4f}")
    print(f"   Max drift: {metrics['max_param_drift_pct']:.1f}%")
    print(f"   Sim-live divergence: {metrics['sim_live_divergence']:.3f}")
    print(f"   Reasons: {reasons if reasons else 'None'}")
    
    # Scenario 2: High divergence failure
    print("\n2. Testing high divergence FAIL scenario:")
    e2_fail = create_mock_e2_report(sim_live_divergence=0.25)  # > 0.15 threshold
    
    ok, reasons, metrics = evaluate(d2_report, thresholds, None, e2_fail)
    
    print(f"   Result: {'PASS' if ok else 'FAIL'}")
    print(f"   Sim-live divergence: {metrics['sim_live_divergence']:.3f}")
    print(f"   Reasons: {reasons}")
    
    # Scenario 3: Low maker share failure
    print("\n3. Testing low maker share FAIL scenario:")
    d2_fail = create_mock_d2_report(hit_rate=0.25, maker_share=0.85)  # < 0.90 threshold
    
    ok, reasons, metrics = evaluate(d2_fail, thresholds, None, None)
    
    print(f"   Result: {'PASS' if ok else 'FAIL'}")
    print(f"   Maker share: {metrics['maker_share_mean']:.4f}")
    print(f"   Reasons: {reasons}")


def demo_config_patches():
    """Demo configuration patch generation."""
    print("\n" + "=" * 40)
    print("Configuration Patches Demo")
    print("=" * 40)
    
    # Champion parameters with mix of whitelisted and non-whitelisted
    champion_params = {
        "k_vola_spread": 1.5,
        "skew_coeff": 0.1,
        "levels_per_side": 4,
        "level_spacing_coeff": 1.0,
        "min_time_in_book_ms": 1000,
        "replace_threshold_bps": 2.0,
        "imbalance_cutoff": 0.8,
        "non_whitelisted_param": 999.0,
        "another_excluded": "test"
    }
    
    print("\nOriginal champion parameters:")
    for key, value in sorted(champion_params.items()):
        print(f"   {key}: {value}")
    
    # Build full patch (whitelisted only)
    full_patch = build_cfg_patch(champion_params)
    
    print("\nFull patch (whitelisted only):")
    print(json.dumps(full_patch, sort_keys=True, indent=2))
    
    # Build canary patch (conservative)
    canary_patch = make_canary_patch(full_patch, shrink=0.5, min_levels=1)
    
    print("\nCanary patch (conservative):")
    print(json.dumps(canary_patch, sort_keys=True, indent=2))
    
    print("\nCanary modifications:")
    print(f"   levels_per_side: {full_patch['levels_per_side']} -> {canary_patch['levels_per_side']} (reduced by 50%)")
    if 'level_spacing_coeff' in full_patch:
        print(f"   level_spacing_coeff: {full_patch['level_spacing_coeff']} -> {canary_patch['level_spacing_coeff']} (increased by 10%)")
    if 'min_time_in_book_ms' in full_patch:
        print(f"   min_time_in_book_ms: {full_patch['min_time_in_book_ms']} -> {canary_patch['min_time_in_book_ms']} (increased by 10%)")


def demo_cli_simulation():
    """Demo CLI output simulation."""
    print("\n" + "=" * 40)
    print("CLI Output Simulation")
    print("=" * 40)
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        # Create mock reports
        d2_report = create_mock_d2_report()
        e2_report = create_mock_e2_report(sim_live_divergence=0.12)
        
        d2_path = tmp_path / "d2_report.json"
        e2_path = tmp_path / "e2_report.json"
        
        with open(d2_path, 'w') as f:
            json.dump(d2_report, f, indent=2)
        with open(e2_path, 'w') as f:
            json.dump(e2_report, f, indent=2)
        
        print(f"\nCreated mock reports:")
        print(f"   D2: {d2_path}")
        print(f"   E2: {e2_path}")
        
        print(f"\nTo test CLI:")
        print(f"python -m src.deploy.rollout \\")
        print(f"  --report {d2_path} \\")
        print(f"  --calibration-report {e2_path} \\")
        print(f"  --symbol BTCUSDT \\")
        print(f"  --round-dp 3")
        
        print(f"\nExpected output format:")
        print(f"GATE RESULT: PASS")
        print(f"symbol: BTCUSDT")
        print(f"timestamp: 2024-XX-XXTXX:XX:XX.XXXXXXZ")
        print(f"")
        print(f"Metrics:")
        print(f"  age_hours: 0.0")
        print(f"  win_ratio: 0.65")
        print(f"  hit_rate: 0.25")
        print(f"  maker_share: 0.95")
        print(f"  pnl_usd: 75.0")
        print(f"  cvar95_usd: -8.0")
        print(f"  drift_max_pct: 12.0")
        print(f"  sim_live_divergence: 0.12")
        print(f"")
        print(f"thresholds: min_hit=0.010, min_maker=0.900, ...")
        print(f"")
        print(f"Reasons: (all gates passed)")
        print(f"")
        print(f"Full patch (JSON):")
        print(f"{{")
        print(f'  "imbalance_cutoff": 0.8,')
        print(f'  "k_vola_spread": 1.5,')
        print(f'  "levels_per_side": 4,')
        print(f'  ...')
        print(f"}}")
        print(f"")
        print(f"Canary patch (JSON):")
        print(f"{{")
        print(f'  "levels_per_side": 2,')
        print(f'  "level_spacing_coeff": 1.1,')
        print(f'  ...')
        print(f"}}")


def main():
    """Run F1 deployment gate demo."""
    demo_gate_evaluation()
    demo_config_patches()
    demo_cli_simulation()
    
    print(f"\n" + "=" * 40)
    print("F1 Deployment Gate Demo Complete!")
    print("=" * 40)
    print("\nKey Features Demonstrated:")
    print("- D2 + E2 report evaluation")
    print("- Gate thresholds validation")
    print("- Parameter drift analysis")
    print("- Sim-live divergence checking")
    print("- Whitelisted config patch generation")
    print("- Conservative canary patch creation")
    print("- CLI dry-run output format")
    print("- Proper exit codes (0=PASS, 2=FAIL, 1=ERROR)")


if __name__ == "__main__":
    main()

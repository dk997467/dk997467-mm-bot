#!/usr/bin/env python3
"""
Quick smoke test for REPORT.md generation with Repro line.
"""

import tempfile
import argparse
from pathlib import Path

from src.research.calibrate import generate_calibration_report_md_content, build_repro_command


def test_report_md_smoke():
    """Quick smoke test of REPORT.md generation."""
    print("Testing REPORT.md generation with Repro line...")
    
    # Mock args for repro command
    args = argparse.Namespace()
    args.symbol = "BTCUSDT"
    args.summaries_dir = "data/research/summaries"
    args.from_utc = "2024-01-01T00:00:00.000Z"
    args.to_utc = "2024-01-02T00:00:00.000Z"
    args.method = "random"
    args.trials = 60
    args.workers = 2
    args.seed = 42
    args.bins_max_bps = 50
    args.percentiles = [0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
    args.weights = [1.0, 1.0, 0.5, 0.25]
    args.reg_l2 = 0.01
    args.round_dp = 6
    args.out = "artifacts/calibration/BTCUSDT"
    args.baseline = None
    args.param_space = None
    
    # Generate repro command
    repro_cmd = build_repro_command(args)
    print(f"Generated repro command: {repro_cmd}")
    
    # Mock data
    meta = {
        "symbol": "BTCUSDT",
        "method": "random",
        "trials": 60,
        "workers": 2,
        "seed": 42,
        "cache_hits": 10,
        "cache_misses": 5,
        "stopped_early": False
    }
    
    live = {
        "live_hit": 0.25,
        "live_maker": None,
        "queue_wait_cdf_ms": [
            {"p": 0.5, "v": 180.0},
            {"p": 0.9, "v": 300.0}
        ],
        "hit_rate_by_bin": {
            "0": {"count": 100, "fills": 25},
            "5": {"count": 80, "fills": 20}
        }
    }
    
    sim_before = None
    sim_after = {
        "sim_hit": 0.24,
        "sim_maker": None
    }
    
    loss_before = None
    loss_after = {
        "KS_queue": 0.1,
        "KS_bins": 0.05,
        "L_hit": 0.02,
        "L_maker": 0.0,
        "L_reg": 0.001,
        "TotalLoss": 0.171
    }
    
    report_data = {
        "go_no_go": {
            "ks_queue_after": 0.1,
            "ks_bins_after": 0.05,
            "w4_effective": 0.0,
            "sim_live_divergence": 0.075,
            "loss_before": 0.0,
            "loss_after": 0.171,
            "loss_regressed": False
        }
    }
    
    # Generate content
    content = generate_calibration_report_md_content(
        meta, live, sim_before, sim_after, loss_before, loss_after, repro_cmd, report_data
    )
    
    print("\nGenerated REPORT.md content:")
    print("=" * 50)
    print(content)
    print("=" * 50)
    
    # Check for key elements
    checks = [
        ("**Repro**:" in content, "Repro line present"),
        ("--seed 42" in content, "Seed in repro command"),
        ("--trials 60" in content, "Trials in repro command"),
        ("## Search Summary" in content, "Search Summary section"),
        ("## LIVE Distributions" in content, "LIVE Distributions section"),
        ("## Go/No-Go" in content, "Go/No-Go section"),
        ("```json" in content, "JSON code blocks"),
        ("REGRESSED" not in content or "OK" in content, "Loss status check")
    ]
    
    print("\nValidation checks:")
    all_passed = True
    for check_passed, description in checks:
        status = "PASS" if check_passed else "FAIL"
        print(f"  {status}: {description}")
        if not check_passed:
            all_passed = False
    
    if all_passed:
        print("\n[OK] All checks passed! REPORT.md generation working correctly.")
        return True
    else:
        print("\n[FAIL] Some checks failed!")
        return False


if __name__ == "__main__":
    success = test_report_md_smoke()
    exit(0 if success else 1)

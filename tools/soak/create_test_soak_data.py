#!/usr/bin/env python3
"""
Generate test soak data for analyze_post_soak.py testing.

Creates realistic ITER_SUMMARY_*.json files with KPI progression.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path


def create_test_data(output_dir: Path, num_iterations: int = 24):
    """Generate test iteration summaries."""
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    base_time = datetime(2025, 10, 16, 12, 0, 0)
    
    # Simulate KPI progression
    for i in range(1, num_iterations + 1):
        # Simulate improving KPIs with some noise
        risk_ratio = 0.38 + (i % 4) * 0.02  # Oscillates: 0.38, 0.40, 0.42, 0.44
        maker_taker = 0.88 + (i % 3) * 0.02  # 0.88, 0.90, 0.92
        net_bps = 2.9 + (i % 5) * 0.1  # 2.9, 3.0, 3.1, 3.2, 3.3
        p95_latency = 280 + (i % 6) * 10  # 280-330ms
        
        # Trigger freeze on iterations 18-20 (stable window)
        freeze_triggered = (18 <= i <= 20)
        
        # Trigger guards occasionally
        cooldown = (i % 7 == 0)
        velocity = (i % 11 == 0)
        oscillation = (i % 13 == 0)
        
        # Signature (simulate A→B→A pattern)
        signatures = ["sig_a1b2c3d4", "sig_e5f6g7h8", "sig_a1b2c3d4"]
        sig_idx = i % len(signatures)
        signature = signatures[sig_idx]
        
        timestamp = base_time + timedelta(minutes=i*5)
        
        iteration_data = {
            "iteration": i,
            "summary": {
                "runtime_utc": timestamp.isoformat() + "Z",
                "risk_ratio": round(risk_ratio, 3),
                "maker_taker_ratio": round(maker_taker, 3),
                "net_bps": round(net_bps, 2),
                "p95_latency_ms": round(p95_latency, 1),
                "adverse_bps_p95": round(1.2 + (i % 3) * 0.1, 2),
                "slippage_bps": round(0.5 + (i % 2) * 0.05, 2),
            },
            "tuning": {
                "applied": not cooldown,
                "proposed_deltas": {
                    "base_spread_bps": 0.01,
                    "min_interval_ms": 5,
                } if not cooldown else {},
                "cooldown_active": cooldown,
                "velocity_violation": velocity,
                "oscillation_detected": oscillation,
                "freeze_triggered": freeze_triggered,
                "freeze_reason": "two_stable_iterations" if freeze_triggered else "",
                "signature": signature,
                "state_hash": signature,
            }
        }
        
        output_file = output_dir / f"ITER_SUMMARY_{i}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(iteration_data, f, indent=2, sort_keys=True, ensure_ascii=True)
        
        print(f"[create_test_data] Generated: {output_file.name}")
    
    print(f"\n[create_test_data] Created {num_iterations} test iteration summaries in {output_dir}")


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate test soak data")
    parser.add_argument(
        "--output",
        type=str,
        default="artifacts/soak/test_run/latest",
        help="Output directory (default: artifacts/soak/test_run/latest)"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=24,
        help="Number of iterations to generate (default: 24)"
    )
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    create_test_data(output_dir, args.iterations)


if __name__ == "__main__":
    main()


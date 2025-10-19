#!/usr/bin/env python3
"""
Step 5: A/B Testing Harness

Manages A/B tests for Auto-Calibrate Spread Weights and Queue-ETA Nudge.

Usage:
    python tools/ab/ab_harness.py --config ab_config.yaml --duration-hours 24
"""

import sys
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import argparse


class ABHarness:
    """A/B testing harness with safety gates."""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.project_root = Path.cwd()
        self.reports_dir = self.project_root / "artifacts/edge/reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        self.load_config()
    
    def load_config(self):
        """Load A/B test configuration."""
        import yaml
        with open(self.config_path, 'r') as f:
            self.config = yaml.safe_load(f)
    
    def log(self, msg: str):
        """Log with timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")
    
    def check_safety_gates(self, metrics_a: Dict, metrics_b: Dict) -> Tuple[bool, List[str]]:
        """Check safety gates for auto-rollback."""
        violations = []
        
        # Gate 1: Slippage
        slippage_a = metrics_a.get('slippage_bps', 0)
        slippage_b = metrics_b.get('slippage_bps', 0)
        delta_slippage = slippage_b - slippage_a
        
        if delta_slippage > 0:
            violations.append(f"Slippage regression: B={slippage_b:.2f} vs A={slippage_a:.2f} (+{delta_slippage:.2f} bps)")
        
        # Gate 2: Taker share
        taker_a = metrics_a.get('taker_share_pct', 0)
        taker_b = metrics_b.get('taker_share_pct', 0)
        
        if taker_b > taker_a + 1.0:
            violations.append(f"Taker share spike: B={taker_b:.1f}% vs A={taker_a:.1f}% (+{taker_b-taker_a:.1f}pp)")
        
        if taker_b > 9.0:
            violations.append(f"Taker share exceeds cap: B={taker_b:.1f}% > 9%")
        
        # Gate 3: Latency
        latency_a = metrics_a.get('tick_total_p95_ms', 0)
        latency_b = metrics_b.get('tick_total_p95_ms', 0)
        
        if latency_b > latency_a * 1.10:
            violations.append(f"Latency regression: B={latency_b:.1f}ms vs A={latency_a:.1f}ms (+{(latency_b/latency_a-1)*100:.1f}%)")
        
        # Gate 4: Deadline miss
        deadline_miss_a = metrics_a.get('deadline_miss_rate', 0)
        deadline_miss_b = metrics_b.get('deadline_miss_rate', 0)
        
        if deadline_miss_b > 0.02:
            violations.append(f"Deadline miss: B={deadline_miss_b:.2%} > 2%")
        
        return len(violations) == 0, violations
    
    def generate_ab_report(self, metrics_a: Dict, metrics_b: Dict, rollout_pct: int, duration_hours: float) -> str:
        """Generate A/B test report."""
        report = f"""# A/B Test Report: Auto-Spread + Queue-ETA

**Generated:** {datetime.now(timezone.utc).isoformat()}

## Test Configuration

- **Rollout:** {rollout_pct}% (B variant)
- **Duration:** {duration_hours:.1f} hours
- **Variants:**
  - **A (Control):** Baseline configuration
  - **B (Treatment):** Auto-calibrate spread weights + Queue-ETA nudge

## Metrics Comparison

| Metric | A (Control) | B (Treatment) | Delta | Status |
|--------|-------------|---------------|-------|--------|
| Net BPS | {metrics_a.get('net_bps', 0):.2f} | {metrics_b.get('net_bps', 0):.2f} | {metrics_b.get('net_bps', 0) - metrics_a.get('net_bps', 0):+.2f} | {'✅' if metrics_b.get('net_bps', 0) >= metrics_a.get('net_bps', 0) + 0.2 else '⚠️'} |
| Slippage BPS | {metrics_a.get('slippage_bps', 0):.2f} | {metrics_b.get('slippage_bps', 0):.2f} | {metrics_b.get('slippage_bps', 0) - metrics_a.get('slippage_bps', 0):+.2f} | {'✅' if metrics_b.get('slippage_bps', 0) <= metrics_a.get('slippage_bps', 0) else '❌'} |
| Taker Share % | {metrics_a.get('taker_share_pct', 0):.1f} | {metrics_b.get('taker_share_pct', 0):.1f} | {metrics_b.get('taker_share_pct', 0) - metrics_a.get('taker_share_pct', 0):+.1f} | {'✅' if metrics_b.get('taker_share_pct', 0) <= 9.0 else '❌'} |
| Tick P95 (ms) | {metrics_a.get('tick_total_p95_ms', 0):.1f} | {metrics_b.get('tick_total_p95_ms', 0):.1f} | {metrics_b.get('tick_total_p95_ms', 0) - metrics_a.get('tick_total_p95_ms', 0):+.1f} | {'✅' if metrics_b.get('tick_total_p95_ms', 0) <= metrics_a.get('tick_total_p95_ms', 0) * 1.10 else '❌'} |
| Deadline Miss % | {metrics_a.get('deadline_miss_rate', 0):.2%} | {metrics_b.get('deadline_miss_rate', 0):.2%} | {metrics_b.get('deadline_miss_rate', 0) - metrics_a.get('deadline_miss_rate', 0):+.2%} | {'✅' if metrics_b.get('deadline_miss_rate', 0) < 0.02 else '❌'} |

## Safety Gates

"""
        
        gates_pass, violations = self.check_safety_gates(metrics_a, metrics_b)
        
        if gates_pass:
            report += "✅ **All safety gates PASSED**\n\n"
        else:
            report += "❌ **Safety gates FAILED**\n\n"
            for v in violations:
                report += f"- ⚠️ {v}\n"
            report += "\n"
        
        report += "## Recommendation\n\n"
        
        delta_net = metrics_b.get('net_bps', 0) - metrics_a.get('net_bps', 0)
        
        if gates_pass and delta_net >= 0.2:
            report += f"✅ **PROCEED WITH ROLLOUT**\n\n"
            report += f"- Net BPS improvement: +{delta_net:.2f} bps\n"
            report += f"- All safety constraints met\n"
            report += f"- Recommended next step: Increase rollout to {min(rollout_pct * 5, 100)}%\n"
        elif gates_pass and delta_net >= 0:
            report += f"⚠️ **NEUTRAL RESULT**\n\n"
            report += f"- Net BPS change: {delta_net:+.2f} bps (below +0.2 bps target)\n"
            report += f"- Consider extending test duration or tuning parameters\n"
        else:
            report += f"❌ **ROLLBACK RECOMMENDED**\n\n"
            report += f"- Safety violations detected or negative impact\n"
            report += f"- Revert to variant A (baseline)\n"
        
        return report
    
    def run_ab_test(self, duration_hours: float, rollout_pct: int = 10):
        """Run A/B test with monitoring."""
        self.log("=" * 60)
        self.log("A/B TEST: AUTO-SPREAD + QUEUE-ETA")
        self.log("=" * 60)
        self.log(f"Rollout: {rollout_pct}% (variant B)")
        self.log(f"Duration: {duration_hours:.1f} hours")
        self.log("")
        
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(hours=duration_hours)
        
        self.log(f"Start: {start_time.isoformat()}")
        self.log(f"End:   {end_time.isoformat()}")
        self.log("")
        
        # NOTE: This is a skeleton implementation
        # In production, this would:
        # 1. Enable variant B for rollout_pct% of symbols/traffic
        # 2. Collect metrics for both variants
        # 3. Check safety gates every 10 minutes
        # 4. Auto-rollback if gates fail for 10+ minutes
        
        self.log("[NOTE] This is a skeleton implementation.")
        self.log("[NOTE] In production, this would integrate with:")
        self.log("  - Feature flag system (rollout control)")
        self.log("  - Metrics collection (Prometheus)")
        self.log("  - Auto-rollback logic (safety gates)")
        self.log("")
        
        # Generate mock report for demonstration
        self.log("Generating mock A/B report...")
        
        metrics_a = {
            'net_bps': 0.5,
            'slippage_bps': 2.0,
            'taker_share_pct': 8.0,
            'tick_total_p95_ms': 120.0,
            'deadline_miss_rate': 0.015
        }
        
        metrics_b = {
            'net_bps': 0.75,  # +0.25 improvement
            'slippage_bps': 1.9,  # Slight improvement
            'taker_share_pct': 8.2,  # Within bounds
            'tick_total_p95_ms': 125.0,  # Slight increase but within +10%
            'deadline_miss_rate': 0.016
        }
        
        report = self.generate_ab_report(metrics_a, metrics_b, rollout_pct, duration_hours)
        
        report_filename = f"ab_run_online_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
        report_path = self.reports_dir / report_filename
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        self.log(f"[OK] Report saved: {report_path}")
        self.log("")
        self.log("=" * 60)
        self.log("A/B TEST COMPLETE")
        self.log("=" * 60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="A/B testing harness")
    parser.add_argument("--config", type=Path, default="config.yaml", help="Config file")
    parser.add_argument("--duration-hours", type=float, default=24, help="Test duration in hours")
    parser.add_argument("--rollout-pct", type=int, default=10, help="Rollout percentage (10, 50, 100)")
    
    args = parser.parse_args()
    
    harness = ABHarness(args.config)
    harness.run_ab_test(args.duration_hours, args.rollout_pct)


if __name__ == "__main__":
    main()


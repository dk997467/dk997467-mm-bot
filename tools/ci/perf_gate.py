#!/usr/bin/env python3
"""
CI Performance Gate - блокирует PR если деградация p95 > +3%.

Usage:
    python tools/ci/perf_gate.py --baseline artifacts/baseline/perf_profile.json --current artifacts/audit/perf_profile.json

Exit codes:
    0 - No regression
    1 - Regression detected (>+3%)
    2 - Error (missing files, etc.)
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any


class PerfGate:
    """
    Performance gate для CI.
    
    Features:
    - Compare current vs baseline p95
    - Fail if p95(stage) > +3%
    - Generate markdown report
    """
    
    REGRESSION_THRESHOLD_PCT = 3.0  # +3% threshold
    
    def __init__(self, baseline_path: Path, current_path: Path):
        """
        Инициализация.
        
        Args:
            baseline_path: Path to baseline perf_profile.json
            current_path: Path to current perf_profile.json
        """
        self.baseline_path = baseline_path
        self.current_path = current_path
        
        self.baseline = self._load_json(baseline_path)
        self.current = self._load_json(current_path)
    
    def _load_json(self, path: Path) -> Dict[str, Any]:
        """Load JSON file."""
        if not path.exists():
            print(f"ERROR: File not found: {path}", file=sys.stderr)
            sys.exit(2)
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"ERROR: Failed to load {path}: {e}", file=sys.stderr)
            sys.exit(2)
    
    def check_regression(self) -> bool:
        """
        Check for performance regression.
        
        Returns:
            True if regression detected, False otherwise
        """
        regression_detected = False
        
        baseline_stages = self.baseline.get("stage_percentiles", {})
        current_stages = self.current.get("stage_percentiles", {})
        
        for stage, baseline_percs in baseline_stages.items():
            current_percs = current_stages.get(stage, {})
            
            baseline_p95 = baseline_percs.get("p95", 0.0)
            current_p95 = current_percs.get("p95", 0.0)
            
            if baseline_p95 == 0:
                continue
            
            # Calculate regression percentage
            regression_pct = ((current_p95 - baseline_p95) / baseline_p95) * 100
            
            if regression_pct > self.REGRESSION_THRESHOLD_PCT:
                regression_detected = True
                print(f"❌ REGRESSION in {stage}: p95 {baseline_p95:.2f}ms → {current_p95:.2f}ms (+{regression_pct:.1f}%)")
            else:
                print(f"✅ OK {stage}: p95 {baseline_p95:.2f}ms → {current_p95:.2f}ms ({regression_pct:+.1f}%)")
        
        return regression_detected
    
    def generate_report(self, output_path: Path) -> None:
        """
        Generate markdown report.
        
        Args:
            output_path: Path to output report (e.g., artifacts/ci/perf_gate_report.md)
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        baseline_stages = self.baseline.get("stage_percentiles", {})
        current_stages = self.current.get("stage_percentiles", {})
        
        lines = [
            "# Performance Gate Report",
            "",
            f"**Baseline**: `{self.baseline_path}`",
            f"**Current**: `{self.current_path}`",
            f"**Threshold**: +{self.REGRESSION_THRESHOLD_PCT}%",
            "",
            "## Stage Comparison (P95)",
            "",
            "| Stage | Baseline (ms) | Current (ms) | Delta | Status |",
            "|-------|---------------|--------------|-------|--------|"
        ]
        
        for stage, baseline_percs in baseline_stages.items():
            current_percs = current_stages.get(stage, {})
            
            baseline_p95 = baseline_percs.get("p95", 0.0)
            current_p95 = current_percs.get("p95", 0.0)
            
            if baseline_p95 == 0:
                delta_str = "N/A"
                status = "⚠️ No baseline"
            else:
                regression_pct = ((current_p95 - baseline_p95) / baseline_p95) * 100
                delta_str = f"{regression_pct:+.1f}%"
                
                if regression_pct > self.REGRESSION_THRESHOLD_PCT:
                    status = "❌ FAIL"
                elif regression_pct > 0:
                    status = "⚠️ Slower"
                else:
                    status = "✅ OK"
            
            lines.append(f"| `{stage}` | {baseline_p95:.2f} | {current_p95:.2f} | {delta_str} | {status} |")
        
        # Additional info
        lines.extend([
            "",
            "## Additional Metrics",
            "",
            f"**Baseline deadline misses**: {self.baseline.get('deadline_miss_pct', 0.0):.2f}%",
            f"**Current deadline misses**: {self.current.get('deadline_miss_pct', 0.0):.2f}%",
            "",
            f"**Baseline total ticks**: {self.baseline.get('total_ticks', 0)}",
            f"**Current total ticks**: {self.current.get('total_ticks', 0)}",
            ""
        ])
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        
        print(f"Report saved to: {output_path}")


def main(argv=None):
    """Main entry point."""
    parser = argparse.ArgumentParser(description="CI Performance Gate")
    parser.add_argument("--baseline", required=True, help="Path to baseline perf_profile.json")
    parser.add_argument("--current", required=True, help="Path to current perf_profile.json")
    parser.add_argument("--report", default="artifacts/ci/perf_gate_report.md", help="Path to output report")
    
    args = parser.parse_args(argv)
    
    baseline_path = Path(args.baseline)
    current_path = Path(args.current)
    report_path = Path(args.report)
    
    gate = PerfGate(baseline_path, current_path)
    
    print("=" * 60)
    print("CI PERFORMANCE GATE")
    print("=" * 60)
    print()
    
    regression_detected = gate.check_regression()
    
    print()
    gate.generate_report(report_path)
    print()
    
    if regression_detected:
        print("❌ FAIL: Performance regression detected (>+3%)")
        print("Fix performance issues before merging")
        return 1
    else:
        print("✅ PASS: No performance regression")
        return 0


if __name__ == "__main__":
    sys.exit(main())

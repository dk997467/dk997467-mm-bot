#!/usr/bin/env python3
"""
Chaos Report Generator - сводный отчёт по chaos testing.

Usage:
    python tools/chaos/report_generator.py --runs artifacts/chaos/runs/*.json --output artifacts/chaos/report.md
"""
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict


class ChaosReportGenerator:
    """
    Генератор сводного отчёта по chaos testing.
    
    Анализирует runs/*.json и создаёт report.md с:
    - Таблица сценариев (scenario, intensity, duration, p95, deadline_miss%, recovery_time)
    - Выводы (pass/fail по сценарию)
    - Рекомендации
    """
    
    def __init__(self, runs_dir: Path, output_path: Path):
        """
        Инициализация.
        
        Args:
            runs_dir: Directory с runs/*.json
            output_path: Output report path
        """
        self.runs_dir = runs_dir
        self.output_path = output_path
        
        self.runs: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = defaultdict(dict)
    
    def load_runs(self) -> None:
        """Load all run JSONs."""
        if not self.runs_dir.exists():
            print(f"ERROR: Runs directory not found: {self.runs_dir}", file=sys.stderr)
            return
        
        for run_file in self.runs_dir.glob("*.json"):
            try:
                with open(run_file, 'r', encoding='utf-8') as f:
                    run_data = json.load(f)
                    self.runs.append(run_data)
            except Exception as e:
                print(f"WARN: Failed to load {run_file}: {e}", file=sys.stderr)
        
        print(f"Loaded {len(self.runs)} runs")
    
    def analyze_runs(self) -> None:
        """Analyze runs and build summary."""
        for run in self.runs:
            scenario = run.get("scenario", "unknown")
            
            if scenario not in self.summary:
                self.summary[scenario] = {
                    "runs": 0,
                    "passed": 0,
                    "failed": 0,
                    "p95_avg": 0.0,
                    "deadline_miss_avg": 0.0,
                    "recovery_time_avg": 0.0
                }
            
            self.summary[scenario]["runs"] += 1
            
            if run.get("result") == "pass":
                self.summary[scenario]["passed"] += 1
            else:
                self.summary[scenario]["failed"] += 1
            
            # Aggregate metrics
            metrics = run.get("metrics", {})
            self.summary[scenario]["p95_avg"] += metrics.get("p95_tick_ms", 0.0)
            self.summary[scenario]["deadline_miss_avg"] += metrics.get("deadline_miss_pct", 0.0)
            self.summary[scenario]["recovery_time_avg"] += metrics.get("recovery_ticks", 0)
        
        # Compute averages
        for scenario, data in self.summary.items():
            if data["runs"] > 0:
                data["p95_avg"] /= data["runs"]
                data["deadline_miss_avg"] /= data["runs"]
                data["recovery_time_avg"] /= data["runs"]
    
    def generate_report(self) -> None:
        """Generate markdown report."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        lines = [
            "# Chaos Engineering Report",
            "",
            f"**Generated**: {Path.ctime(Path(__file__)) if Path(__file__).exists() else 'unknown'}",
            f"**Total Runs**: {len(self.runs)}",
            "",
            "## Scenario Summary",
            "",
            "| Scenario | Runs | Passed | Failed | P95 (ms) | Deadline Miss % | Recovery (ticks) | Status |",
            "|----------|------|--------|--------|----------|-----------------|------------------|--------|"
        ]
        
        for scenario, data in sorted(self.summary.items()):
            pass_rate = (data["passed"] / data["runs"]) * 100 if data["runs"] > 0 else 0
            status = "✅ PASS" if pass_rate == 100 else f"⚠️ {pass_rate:.0f}%"
            
            lines.append(
                f"| `{scenario}` | {data['runs']} | {data['passed']} | {data['failed']} | "
                f"{data['p95_avg']:.1f} | {data['deadline_miss_avg']:.2f} | "
                f"{data['recovery_time_avg']:.1f} | {status} |"
            )
        
        # Findings
        lines.extend([
            "",
            "## Key Findings",
            ""
        ])
        
        for scenario, data in sorted(self.summary.items()):
            if data["failed"] > 0:
                lines.append(f"- ⚠️ **{scenario}**: {data['failed']} failures out of {data['runs']} runs")
            
            if data["p95_avg"] > 200:
                lines.append(f"- ⚠️ **{scenario}**: P95 ({data['p95_avg']:.1f}ms) exceeds target 200ms")
            
            if data["deadline_miss_avg"] > 2.0:
                lines.append(f"- ⚠️ **{scenario}**: Deadline miss ({data['deadline_miss_avg']:.2f}%) exceeds target 2%")
            
            if data["recovery_time_avg"] > 3.0:
                lines.append(f"- ⚠️ **{scenario}**: Recovery time ({data['recovery_time_avg']:.1f} ticks) exceeds target 3 ticks")
        
        # Recommendations
        lines.extend([
            "",
            "## Recommendations",
            "",
            "### High Priority",
            "- Review scenarios with >10% failure rate",
            "- Investigate P95 >200ms (may need backoff tuning)",
            "",
            "### Medium Priority",
            "- Monitor deadline_miss% in production (<2% threshold)",
            "- Validate recovery time (should be ≤3 ticks)",
            "",
            "### Low Priority",
            "- Consider adding more scenarios (MEM_PRESSURE, RATE_LIMIT_STORM)",
            "- Extend burst duration for longer stress testing",
            ""
        ])
        
        # Write report
        with open(self.output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        
        print(f"Report saved to: {self.output_path}")


def main(argv=None):
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Chaos Report Generator")
    parser.add_argument("--runs", required=True, help="Path to runs directory (artifacts/chaos/runs)")
    parser.add_argument("--output", default="artifacts/chaos/report.md", help="Output report path")
    
    args = parser.parse_args(argv)
    
    runs_dir = Path(args.runs)
    output_path = Path(args.output)
    
    generator = ChaosReportGenerator(runs_dir, output_path)
    
    print("=" * 60)
    print("CHAOS REPORT GENERATOR")
    print("=" * 60)
    print()
    
    generator.load_runs()
    generator.analyze_runs()
    generator.generate_report()
    
    print()
    print("✅ Report generation complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Visualize shadow baseline metrics with ASCII charts.

Generates visual representations of p50/p95/p99 latencies for quick analysis.
"""
import argparse
import orjson
from pathlib import Path


def generate_bar_chart(values: dict, title: str, max_width: int = 60) -> str:
    """Generate ASCII bar chart."""
    lines = []
    lines.append(f"\n{title}")
    lines.append("=" * len(title))
    
    # Find max value for scaling
    max_val = max(values.values())
    
    for label, value in values.items():
        # Scale bar to max_width
        bar_length = int((value / max_val) * max_width)
        bar = "█" * bar_length
        lines.append(f"{label:20s} {bar} {value:.1f} ms")
    
    lines.append("")
    return "\n".join(lines)


def visualize_baseline(stage_budgets_path: str, output_path: str = None):
    """Generate visualizations from stage_budgets.json."""
    # Read baseline data
    with open(stage_budgets_path, "rb") as f:
        data = orjson.loads(f.read())
    
    lines = []
    lines.append("# Shadow Baseline Visualization")
    lines.append("")
    lines.append(f"**Generated**: {data['generated_at']}")
    lines.append(f"**Duration**: {data['test_duration_min']} minutes")
    lines.append(f"**Ticks**: {data['tick_count']}")
    lines.append("")
    
    # Stage p95 latencies
    stage_p95 = {stage: info["p95_ms"] for stage, info in data["stages"].items()}
    lines.append(generate_bar_chart(stage_p95, "Stage Latencies (p95)"))
    
    # Stage p99 latencies
    stage_p99 = {stage: info["p99_ms"] for stage, info in data["stages"].items()}
    lines.append(generate_bar_chart(stage_p99, "Stage Latencies (p99)"))
    
    # Tick total summary
    tick_total = data["tick_total"]
    lines.append("\n## Tick Total Latency Distribution")
    lines.append("=" * 40)
    lines.append(f"p50: {tick_total['p50_ms']:.1f} ms")
    lines.append(f"p95: {tick_total['p95_ms']:.1f} ms  (target: <= {tick_total['deadline_ms']:.0f} ms)")
    lines.append(f"p99: {tick_total['p99_ms']:.1f} ms")
    lines.append(f"max: {tick_total['max_ms']:.1f} ms")
    lines.append(f"deadline_miss_rate: {tick_total['deadline_miss_rate']:.2%}")
    lines.append("")
    
    # Percentile comparison
    percentiles = {
        "p50": {stage: info["p50_ms"] for stage, info in data["stages"].items()},
        "p95": {stage: info["p95_ms"] for stage, info in data["stages"].items()},
        "p99": {stage: info["p99_ms"] for stage, info in data["stages"].items()},
    }
    
    lines.append("\n## Percentile Comparison")
    lines.append("=" * 40)
    lines.append(f"{'Stage':<20s} {'p50':>8s} {'p95':>8s} {'p99':>8s}")
    lines.append("-" * 48)
    for stage in data["stages"].keys():
        p50 = percentiles["p50"][stage]
        p95 = percentiles["p95"][stage]
        p99 = percentiles["p99"][stage]
        lines.append(f"{stage:<20s} {p50:>7.1f}  {p95:>7.1f}  {p99:>7.1f}")
    
    # Tick total row
    lines.append("-" * 48)
    lines.append(f"{'TICK_TOTAL':<20s} {tick_total['p50_ms']:>7.1f}  {tick_total['p95_ms']:>7.1f}  {tick_total['p99_ms']:>7.1f}")
    lines.append("")
    
    # Gate status
    lines.append("\n## Gate Status")
    lines.append("=" * 40)
    
    # Calculate gate pass/fail
    fetch_md_p95 = data["stages"]["FetchMDStage"]["p95_ms"]
    fetch_md_pass = fetch_md_p95 <= 35.0
    
    tick_total_pass = tick_total["p95_ms"] <= 150.0
    deadline_miss_pass = tick_total["deadline_miss_rate"] < 0.02
    
    all_passed = fetch_md_pass and tick_total_pass and deadline_miss_pass
    
    status_icon = "[PASS]" if fetch_md_pass else "[FAIL]"
    lines.append(f"{status_icon} fetch_md p95: {fetch_md_p95:.1f} ms (target: <= 35 ms)")
    
    status_icon = "[PASS]" if tick_total_pass else "[FAIL]"
    lines.append(f"{status_icon} tick_total p95: {tick_total['p95_ms']:.1f} ms (target: <= 150 ms)")
    
    status_icon = "[PASS]" if deadline_miss_pass else "[FAIL]"
    lines.append(f"{status_icon} deadline_miss: {tick_total['deadline_miss_rate']:.2%} (target: < 2%)")
    
    lines.append("")
    if all_passed:
        lines.append("[PASS] ALL GATES PASSED")
    else:
        lines.append("[FAIL] SOME GATES FAILED")
    lines.append("")
    
    # Write output
    output = "\n".join(lines)
    
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Visualization saved to: {output_path}")
    else:
        print(output)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Visualize shadow baseline metrics")
    parser.add_argument(
        "--stage-budgets",
        type=str,
        default="artifacts/baseline/stage_budgets.json",
        help="Path to stage_budgets.json"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (default: print to stdout)"
    )
    
    args = parser.parse_args()
    
    visualize_baseline(args.stage_budgets, args.output)


if __name__ == "__main__":
    main()



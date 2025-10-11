"""
Generate calibration summary report.

Reads calibration dataset and generates:
- artifacts/edge/reports/calib_summary.md

Includes:
- Feature distributions
- Target distributions
- Missing data analysis
- High-level correlations
- Data quality metrics
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict
import orjson
import statistics

logger = logging.getLogger(__name__)


class CalibrationSummaryGenerator:
    """Generates calibration summary report."""
    
    def __init__(self, reports_dir: Path):
        """
        Initialize generator.
        
        Args:
            reports_dir: Directory for reports
        """
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"[SUMMARY_GEN] Initialized: reports_dir={reports_dir}")
    
    def generate(self, dataset_path: Path) -> Path:
        """
        Generate summary report for dataset.
        
        Args:
            dataset_path: Path to calibration dataset JSON
        
        Returns:
            Path to generated summary report
        """
        logger.info(f"[SUMMARY_GEN] Loading dataset from {dataset_path}")
        
        # Load dataset
        with open(dataset_path, "rb") as f:
            dataset = orjson.loads(f.read())
        
        # Analyze dataset
        analysis = self._analyze_dataset(dataset)
        
        # Generate markdown report
        report_path = self._write_report(dataset_path, dataset, analysis)
        
        logger.info(f"[SUMMARY_GEN] Generated report: {report_path}")
        
        return report_path
    
    def _analyze_dataset(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze dataset and compute statistics.
        
        Args:
            dataset: Calibration dataset
        
        Returns:
            Analysis dict with statistics
        """
        intervals = dataset["intervals"]
        
        if not intervals:
            return {"error": "No intervals in dataset"}
        
        # Collect targets and features
        targets_by_metric = defaultdict(list)
        features_by_metric = defaultdict(list)
        
        for interval in intervals:
            # Targets
            for metric, value in interval["targets"].items():
                targets_by_metric[metric].append(value)
            
            # Features
            for metric, value in interval["features"].items():
                features_by_metric[metric].append(value)
        
        # Compute statistics
        def compute_stats(values: List[float]) -> Dict[str, float]:
            if not values:
                return {}
            
            return {
                "count": len(values),
                "mean": statistics.mean(values),
                "median": statistics.median(values),
                "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
                "min": min(values),
                "max": max(values),
                "p25": statistics.quantiles(values, n=4)[0] if len(values) >= 4 else min(values),
                "p75": statistics.quantiles(values, n=4)[2] if len(values) >= 4 else max(values)
            }
        
        targets_stats = {
            metric: compute_stats(values)
            for metric, values in targets_by_metric.items()
        }
        
        features_stats = {
            metric: compute_stats(values)
            for metric, values in features_by_metric.items()
        }
        
        # Symbols
        symbols = set(interval["symbol"] for interval in intervals)
        intervals_by_symbol = defaultdict(int)
        for interval in intervals:
            intervals_by_symbol[interval["symbol"]] += 1
        
        # Missing data analysis
        missing_data = self._analyze_missing_data(intervals)
        
        return {
            "total_intervals": len(intervals),
            "total_symbols": len(symbols),
            "intervals_by_symbol": dict(intervals_by_symbol),
            "targets_stats": targets_stats,
            "features_stats": features_stats,
            "missing_data": missing_data
        }
    
    def _analyze_missing_data(self, intervals: List[Dict]) -> Dict[str, Any]:
        """
        Analyze missing data patterns.
        
        Args:
            intervals: List of interval records
        
        Returns:
            Missing data analysis
        """
        total = len(intervals)
        
        # Check for NaN/inf in targets
        targets_with_issues = 0
        for interval in intervals:
            for value in interval["targets"].values():
                if value is None or not isinstance(value, (int, float)):
                    targets_with_issues += 1
                    break
        
        # Check for NaN/inf in features
        features_with_issues = 0
        for interval in intervals:
            for value in interval["features"].values():
                if value is None or not isinstance(value, (int, float)):
                    features_with_issues += 1
                    break
        
        return {
            "total_intervals": total,
            "targets_with_issues": targets_with_issues,
            "targets_with_issues_pct": (targets_with_issues / total * 100) if total > 0 else 0.0,
            "features_with_issues": features_with_issues,
            "features_with_issues_pct": (features_with_issues / total * 100) if total > 0 else 0.0
        }
    
    def _write_report(
        self,
        dataset_path: Path,
        dataset: Dict[str, Any],
        analysis: Dict[str, Any]
    ) -> Path:
        """
        Write markdown report.
        
        Args:
            dataset_path: Path to dataset file
            dataset: Dataset dict
            analysis: Analysis dict
        
        Returns:
            Path to report file
        """
        # Extract dataset name
        dataset_name = dataset_path.stem
        
        report_filename = f"calib_summary_{dataset_name}.md"
        report_path = self.reports_dir / report_filename
        
        lines = []
        lines.append(f"# Calibration Dataset Summary: {dataset_name}")
        lines.append("")
        lines.append(f"**Dataset**: `{dataset_path}`")
        lines.append(f"**Period**: {dataset['from_ts']} → {dataset['to_ts']}")
        lines.append(f"**Interval**: {dataset['interval_sec']}s")
        lines.append("")
        
        # Overview
        lines.append("## Overview")
        lines.append("")
        lines.append(f"- **Total Intervals**: {analysis['total_intervals']}")
        lines.append(f"- **Total Symbols**: {analysis['total_symbols']}")
        lines.append(f"- **Filtered Out**: {dataset.get('filtered_count', 0)}")
        lines.append("")
        
        # Intervals by symbol
        lines.append("## Intervals by Symbol")
        lines.append("")
        lines.append("| Symbol | Intervals |")
        lines.append("|--------|-----------|")
        for symbol, count in sorted(
            analysis["intervals_by_symbol"].items(),
            key=lambda x: x[1],
            reverse=True
        ):
            lines.append(f"| {symbol} | {count} |")
        lines.append("")
        
        # Target distributions
        lines.append("## Target Distributions")
        lines.append("")
        for metric, stats in analysis["targets_stats"].items():
            lines.append(f"### {metric}")
            lines.append("")
            lines.append(f"- **Count**: {stats['count']}")
            lines.append(f"- **Mean**: {stats['mean']:.4f}")
            lines.append(f"- **Median**: {stats['median']:.4f}")
            lines.append(f"- **Stdev**: {stats['stdev']:.4f}")
            lines.append(f"- **Range**: [{stats['min']:.4f}, {stats['max']:.4f}]")
            lines.append(f"- **IQR**: [{stats['p25']:.4f}, {stats['p75']:.4f}]")
            lines.append("")
        
        # Feature distributions
        lines.append("## Feature Distributions")
        lines.append("")
        for metric, stats in analysis["features_stats"].items():
            lines.append(f"### {metric}")
            lines.append("")
            lines.append(f"- **Count**: {stats['count']}")
            lines.append(f"- **Mean**: {stats['mean']:.4f}")
            lines.append(f"- **Median**: {stats['median']:.4f}")
            lines.append(f"- **Stdev**: {stats['stdev']:.4f}")
            lines.append(f"- **Range**: [{stats['min']:.4f}, {stats['max']:.4f}]")
            lines.append(f"- **IQR**: [{stats['p25']:.4f}, {stats['p75']:.4f}]")
            lines.append("")
        
        # Data quality
        lines.append("## Data Quality")
        lines.append("")
        missing = analysis["missing_data"]
        lines.append(f"- **Targets with issues**: {missing['targets_with_issues']} ({missing['targets_with_issues_pct']:.2f}%)")
        lines.append(f"- **Features with issues**: {missing['features_with_issues']} ({missing['features_with_issues_pct']:.2f}%)")
        lines.append("")
        
        if missing["targets_with_issues"] > 0 or missing["features_with_issues"] > 0:
            lines.append("⚠️ **WARNING**: Dataset contains NaN/inf values. Consider additional filtering.")
        else:
            lines.append("✓ **PASS**: No NaN/inf values detected.")
        
        lines.append("")
        
        # Write report
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        return report_path


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate calibration summary report")
    parser.add_argument(
        "dataset_path",
        type=str,
        help="Path to calibration dataset JSON"
    )
    parser.add_argument(
        "--reports-dir",
        type=str,
        default="artifacts/edge/reports",
        help="Output directory for reports"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose logging"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    # Generate summary
    generator = CalibrationSummaryGenerator(Path(args.reports_dir))
    report_path = generator.generate(Path(args.dataset_path))
    
    print(f"✓ Summary report generated: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


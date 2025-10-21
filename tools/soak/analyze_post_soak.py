#!/usr/bin/env python3
"""
Post-Soak Analyzer V2

Analyzes iteration summaries, builds trends, detects violations,
and generates actionable recommendations with sparklines and status reports.

Usage:
    python -m tools.soak.analyze_post_soak --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json"
    python -m tools.soak.analyze_post_soak --iter-glob "artifacts/soak/latest/ITER_SUMMARY_*.json" --exit-on-crit
"""

import argparse
import glob
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


# Sparkline characters (8 levels)
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


def load_windows(iter_glob: str,
                 symbols_filter: Optional[List[str]] = None) -> Dict[str,
                                                                     List[Dict[str,
                                                                               Any]]]:
    """
    Load iteration summary windows from JSON files.

    Args:
        iter_glob: Glob pattern for ITER_SUMMARY files
        symbols_filter: Optional list of symbols to filter

    Returns:
        Dict mapping symbol to list of window data
    """
    files = sorted(glob.glob(iter_glob))

    if not files:
        print(f"[ERROR] No files matched pattern: {iter_glob}")
        return {}

    print(f"[INFO] Found {len(files)} iteration files")

    windows_by_symbol = defaultdict(list)

    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Support both flat and nested schemas
            if "symbol" in data:
                # Flat schema
                symbol = data["symbol"]
                window_data = data
            elif "summary" in data and "symbol" in data["summary"]:
                # Nested schema
                symbol = data["summary"]["symbol"]
                window_data = data["summary"]
            else:
                print(
                    f"[WARN] No symbol found in {
                        Path(file_path).name}, skipping")
                continue

            # Apply symbol filter
            if symbols_filter and symbol not in symbols_filter:
                continue

            # Extract metrics
            metrics = {
                "edge_bps": window_data.get("net_bps") or window_data.get("edge_bps"),
                "maker_taker_ratio": window_data.get("maker_taker_ratio"),
                "p95_latency_ms": window_data.get("p95_latency_ms"),
                "risk_ratio": window_data.get("risk_ratio"),
            }

            # Metadata
            metadata = {
                "commit": data.get("commit"),
                "profile": data.get("profile"),
                "source": data.get("source"),
                "notes": data.get("notes"),
            }

            windows_by_symbol[symbol].append({
                "metrics": metrics,
                "metadata": metadata,
                "file": Path(file_path).name
            })

        except Exception as e:
            print(f"[WARN] Failed to load {Path(file_path).name}: {e}")
            continue

    return dict(windows_by_symbol)


def generate_sparkline(values: List[float], width: int = 10) -> str:
    """
    Generate ASCII sparkline from values.

    Args:
        values: List of numeric values
        width: Number of characters in sparkline

    Returns:
        Sparkline string
    """
    if not values:
        return "─" * width

    # Filter out NaN/inf
    clean_values = [v for v in values if v is not None and math.isfinite(v)]

    if not clean_values:
        return "─" * width

    # Sample values if more than width
    if len(clean_values) > width:
        step = len(clean_values) / width
        sampled = [clean_values[int(i * step)] for i in range(width)]
    else:
        sampled = clean_values

    # Normalize to [0, 1]
    min_val = min(sampled)
    max_val = max(sampled)

    if max_val == min_val:
        # All values the same
        return SPARKLINE_CHARS[4] * len(sampled)

    normalized = [(v - min_val) / (max_val - min_val) for v in sampled]

    # Map to sparkline chars
    sparkline = ""
    for norm in normalized:
        idx = min(int(norm * len(SPARKLINE_CHARS)), len(SPARKLINE_CHARS) - 1)
        sparkline += SPARKLINE_CHARS[idx]

    return sparkline


def calculate_trend(values: List[float]) -> Tuple[str, float]:
    """
    Calculate linear trend (slope) and return symbol.

    Args:
        values: List of numeric values

    Returns:
        Tuple of (trend_symbol, slope)
    """
    clean_values = [v for v in values if v is not None and math.isfinite(v)]

    if len(clean_values) < 2:
        return "≈", 0.0

    # Simple linear regression
    n = len(clean_values)
    x = list(range(n))
    y = clean_values

    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi ** 2 for xi in x)

    # Slope: (n*sum_xy - sum_x*sum_y) / (n*sum_x2 - sum_x^2)
    denominator = n * sum_x2 - sum_x ** 2

    if denominator == 0:
        return "≈", 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denominator

    # Classify trend
    # Threshold: significant if slope > 5% of mean per window
    mean_val = sum_y / n
    threshold = abs(mean_val) * 0.05 if mean_val != 0 else 0.1

    if slope > threshold:
        return "↑", slope
    elif slope < -threshold:
        return "↓", slope
    else:
        return "≈", slope


def detect_violations(
    symbol: str,
    metrics_series: Dict[str, List[float]],
    thresholds: Dict[str, Dict[str, float]]
) -> List[Dict[str, Any]]:
    """
    Detect metric violations (WARN/CRIT).

    Args:
        symbol: Symbol name
        metrics_series: Dict of metric name to list of values
        thresholds: Dict of thresholds (warn_edge, crit_edge, etc.)

    Returns:
        List of violation dicts
    """
    violations = []

    for metric_name, values in metrics_series.items():
        clean_values = [
            v for v in values if v is not None and math.isfinite(v)]

        if not clean_values:
            violations.append({
                "symbol": symbol,
                "metric": metric_name,
                "level": "WARN",
                "window_index": None,
                "value": None,
                "threshold": None,
                "note": "No valid data"
            })
            continue

        # Check each window
        for idx, value in enumerate(clean_values):
            violation = None

            if metric_name == "edge_bps":
                crit_thresh = thresholds.get("crit_edge", 2.5)
                warn_thresh = thresholds.get("warn_edge", 3.0)

                if value < crit_thresh:
                    violation = {
                        "symbol": symbol,
                        "metric": metric_name,
                        "level": "CRIT",
                        "window_index": idx,
                        "value": value,
                        "threshold": crit_thresh,
                        "note": f"Edge below critical threshold ({
                            value:.2f} < {crit_thresh})"}
                elif value < warn_thresh:
                    violation = {
                        "symbol": symbol,
                        "metric": metric_name,
                        "level": "WARN",
                        "window_index": idx,
                        "value": value,
                        "threshold": warn_thresh,
                        "note": f"Edge below warning threshold ({
                            value:.2f} < {warn_thresh})"}

            elif metric_name == "maker_taker_ratio":
                crit_thresh = thresholds.get("crit_maker", 0.70)
                warn_thresh = thresholds.get("warn_maker", 0.75)

                if value < crit_thresh:
                    violation = {
                        "symbol": symbol,
                        "metric": metric_name,
                        "level": "CRIT",
                        "window_index": idx,
                        "value": value,
                        "threshold": crit_thresh,
                        "note": f"Maker/taker below critical threshold ({value:.3f} < {crit_thresh})"
                    }
                elif value < warn_thresh:
                    violation = {
                        "symbol": symbol,
                        "metric": metric_name,
                        "level": "WARN",
                        "window_index": idx,
                        "value": value,
                        "threshold": warn_thresh,
                        "note": f"Maker/taker below warning threshold ({value:.3f} < {warn_thresh})"
                    }

            elif metric_name == "p95_latency_ms":
                crit_thresh = thresholds.get("crit_lat", 350)
                warn_thresh = thresholds.get("warn_lat", 330)

                if value > crit_thresh:
                    violation = {
                        "symbol": symbol,
                        "metric": metric_name,
                        "level": "CRIT",
                        "window_index": idx,
                        "value": value,
                        "threshold": crit_thresh,
                        "note": f"Latency above critical threshold ({
                            value:.0f} > {crit_thresh})"}
                elif value > warn_thresh:
                    violation = {
                        "symbol": symbol,
                        "metric": metric_name,
                        "level": "WARN",
                        "window_index": idx,
                        "value": value,
                        "threshold": warn_thresh,
                        "note": f"Latency above warning threshold ({
                            value:.0f} > {warn_thresh})"}

            elif metric_name == "risk_ratio":
                crit_thresh = thresholds.get("crit_risk", 0.40)
                warn_thresh = thresholds.get("warn_risk", 0.40)

                if value >= crit_thresh:
                    violation = {
                        "symbol": symbol,
                        "metric": metric_name,
                        "level": "CRIT",
                        "window_index": idx,
                        "value": value,
                        "threshold": crit_thresh,
                        "note": f"Risk at/above critical threshold ({value:.3f} >= {crit_thresh})"
                    }
                elif value > warn_thresh * 0.9:  # 90% of warn threshold
                    violation = {
                        "symbol": symbol,
                        "metric": metric_name,
                        "level": "WARN",
                        "window_index": idx,
                        "value": value,
                        "threshold": warn_thresh,
                        "note": f"Risk approaching warning threshold ({
                            value:.3f} near {warn_thresh})"}

            if violation:
                violations.append(violation)

    return violations


def generate_recommendations(
    symbol: str,
    metrics_series: Dict[str, List[float]],
    violations: List[Dict[str, Any]]
) -> List[str]:
    """
    Generate actionable recommendations in Russian.

    Args:
        symbol: Symbol name
        metrics_series: Dict of metric name to list of values
        violations: List of detected violations

    Returns:
        List of recommendation strings
    """
    recommendations = []

    # Group violations by metric
    violations_by_metric = defaultdict(list)
    for v in violations:
        if v["symbol"] == symbol:
            violations_by_metric[v["metric"]].append(v)

    # Calculate current medians
    current_vals = {}
    for metric, values in metrics_series.items():
        clean = [v for v in values if v is not None and math.isfinite(v)]
        if clean:
            current_vals[metric] = sorted(clean)[len(clean) // 2]

    # Maker/taker recommendations
    if "maker_taker_ratio" in violations_by_metric:
        level = max(v["level"]
                    for v in violations_by_metric["maker_taker_ratio"])
        current = current_vals.get("maker_taker_ratio", 0)

        if level == "CRIT":
            recommendations.append(
                f"**Maker/Taker КРИТИЧНО низкий ({current:.3f})**: "
                f"Увеличить плотность post_only ордеров на 20-30%, "
                f"уменьшить edge на 15-20% для повышения заполнений, "
                f"повысить touch_dwell_ms на 50-100ms, "
                f"добавить 2-3 дополнительных слоя на best bid/ask."
            )
        else:
            recommendations.append(
                f"**Maker/Taker низкий ({current:.3f})**: "
                f"Увеличить post_only плотность на 10-15%, "
                f"уменьшить edge на 5-10%, "
                f"повысить touch_dwell_ms на 20-30ms."
            )

    # Latency recommendations
    if "p95_latency_ms" in violations_by_metric:
        level = max(v["level"] for v in violations_by_metric["p95_latency_ms"])
        current = current_vals.get("p95_latency_ms", 0)

        if level == "CRIT":
            recommendations.append(
                f"**Latency КРИТИЧНО высокий ({current:.0f}ms)**: "
                f"Срочно уменьшить частоту перерасчёта на 30-50%, "
                f"снизить частоту ребидов (увеличить min_rebid_delta), "
                f"проверить сетевое подключение и clock drift, "
                f"отключить неприоритетные вычисления в hot path."
            )
        else:
            recommendations.append(
                f"**Latency повышенный ({current:.0f}ms)**: "
                f"Уменьшить частоту перерасчёта на 10-20%, "
                f"снизить частоту ребидов, "
                f"проверить профилировщик на hot spots."
            )

    # Risk recommendations
    if "risk_ratio" in violations_by_metric:
        level = max(v["level"] for v in violations_by_metric["risk_ratio"])
        current = current_vals.get("risk_ratio", 0)

        if level == "CRIT":
            recommendations.append(
                f"**Risk КРИТИЧНО высокий ({current:.3f})**: "
                f"Немедленно ужесточить guards: уменьшить max_position на 30-40%, "
                f"увеличить cooldown_after_adverse на 2-3x, "
                f"повысить adverse_move_threshold на 20-30%, "
                f"активировать emergency_stop если доступно."
            )
        else:
            recommendations.append(
                f"**Risk повышенный ({current:.3f})**: "
                f"Ужесточить guards: уменьшить max_position на 15-20%, "
                f"увеличить cooldown_after_adverse на 1.5x, "
                f"повысить adverse_move_threshold на 10-15%."
            )

    # Edge recommendations
    if "edge_bps" in violations_by_metric:
        level = max(v["level"] for v in violations_by_metric["edge_bps"])
        current_edge = current_vals.get("edge_bps", 0)
        current_maker = current_vals.get("maker_taker_ratio", 0)

        if level == "CRIT":
            if current_maker > 0.75:
                # Good maker, but low edge - tighten spread
                recommendations.append(
                    f"**Edge КРИТИЧНО низкий ({current_edge:.2f} bps) при нормальном maker**: "
                    f"Чуть ужать spread на 5-10%, "
                    f"активировать maker_boost режим, "
                    f"проверить что taker spread не слишком широкий."
                )
            else:
                # Low edge and low maker - more aggressive
                recommendations.append(
                    f"**Edge КРИТИЧНО низкий ({current_edge:.2f} bps)**: "
                    f"Ужать spread на 15-20%, "
                    f"увеличить агрессивность maker ордеров, "
                    f"активировать maker_boost, "
                    f"проверить конкурентную обстановку на бирже."
                )
        else:
            recommendations.append(
                f"**Edge низкий ({current_edge:.2f} bps)**: "
                f"Чуть ужать spread на 5-7%, "
                f"рассмотреть активацию maker_boost."
            )

    # If no violations, give positive feedback
    if not recommendations:
        recommendations.append(
            "✅ Все метрики в норме, продолжайте текущую стратегию.")

    return recommendations


def generate_analysis_report(
    windows_by_symbol: Dict[str, List[Dict[str, Any]]],
    thresholds: Dict[str, float],
    min_windows: int,
    out_dir: Path
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    Generate POST_SOAK_ANALYSIS.md report.

    Returns:
        Tuple of (crit_count, all_violations)
    """
    lines = [
        "# Post-Soak Analysis Report V2",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        ""
    ]

    # Count total windows
    total_windows = sum(len(windows) for windows in windows_by_symbol.values())
    lines.append(f"**Total Windows:** {total_windows}")
    lines.append(f"**Symbols:** {len(windows_by_symbol)}")
    lines.append("")

    # Check min windows
    if total_windows < min_windows:
        lines.append(
            f"⚠️ **WARNING**: Windows < min_windows (actual={total_windows}, required={min_windows}) — proceeding with WARN")
    lines.append("")

    # Collect metadata
    all_commits = set()
    all_profiles = set()

    for windows in windows_by_symbol.values():
        for window in windows:
            meta = window.get("metadata", {})
            if meta.get("commit"):
                all_commits.add(meta["commit"])
            if meta.get("profile"):
                all_profiles.add(meta["profile"])

    if all_commits:
        lines.append(f"**Commits:** {', '.join(sorted(all_commits))}")
    if all_profiles:
        lines.append(f"**Profiles:** {', '.join(sorted(all_profiles))}")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-symbol analysis
    all_violations = []
    crit_count = 0

    for symbol in sorted(windows_by_symbol.keys()):
        windows = windows_by_symbol[symbol]

        lines.append(f"## {symbol}")
        lines.append("")
        lines.append(f"**Windows:** {len(windows)}")
        lines.append("")

        # Extract metrics series
        metrics_series = {
            "edge_bps": [],
            "maker_taker_ratio": [],
            "p95_latency_ms": [],
            "risk_ratio": []
        }

        for window in windows:
            for metric_name in metrics_series.keys():
                value = window["metrics"].get(metric_name)
                metrics_series[metric_name].append(value)

        # Build table
        lines.append(
            "| Metric | Current | Min | Max | Median | Sparkline | Trend | Status |")
        lines.append(
            "|--------|---------|-----|-----|--------|-----------|-------|--------|")

        # Detect violations
        violations = detect_violations(symbol, metrics_series, thresholds)
        all_violations.extend(violations)

        # Count CRIT violations for this symbol
        symbol_crit = sum(1 for v in violations if v["level"] == "CRIT")
        crit_count += symbol_crit

        for metric_name, values in metrics_series.items():
            clean_values = [
                v for v in values if v is not None and math.isfinite(v)]

            if not clean_values:
                lines.append(
                    f"| {metric_name} | N/A | N/A | N/A | N/A | ─────── | ≈ | WARN |")
                continue

            current = clean_values[-1]
            min_val = min(clean_values)
            max_val = max(clean_values)
            median_val = sorted(clean_values)[len(clean_values) // 2]

            sparkline = generate_sparkline(clean_values, width=10)
            trend_symbol, _ = calculate_trend(clean_values)

            # Determine status
            metric_violations = [
                v for v in violations if v["metric"] == metric_name]
            if any(v["level"] == "CRIT" for v in metric_violations):
                status = "🔴 CRIT"
            elif any(v["level"] == "WARN" for v in metric_violations):
                status = "🟡 WARN"
            else:
                status = "✅ OK"

            # Format values
            if metric_name == "p95_latency_ms":
                current_str = f"{current:.0f}ms"
                min_str = f"{min_val:.0f}"
                max_str = f"{max_val:.0f}"
                median_str = f"{median_val:.0f}"
            elif metric_name in ["maker_taker_ratio", "risk_ratio"]:
                current_str = f"{current:.3f}"
                min_str = f"{min_val:.3f}"
                max_str = f"{max_val:.3f}"
                median_str = f"{median_val:.3f}"
            else:  # edge_bps
                current_str = f"{current:.2f}"
                min_str = f"{min_val:.2f}"
                max_str = f"{max_val:.2f}"
                median_str = f"{median_val:.2f}"

            lines.append(
                f"| {metric_name} | {current_str} | {min_str} | {max_str} | {median_str} | {sparkline} | {trend_symbol} | {status} |")

        lines.append("")

        # List violations for this symbol
        if metric_violations := [
                v for v in violations if v["symbol"] == symbol]:
            lines.append("**Violations:**")
            for v in metric_violations:
                lines.append(f"- {v['level']}: {v['note']}")
    lines.append("")

    # Summary
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")

    warn_count = sum(1 for v in all_violations if v["level"] == "WARN")
    ok_count = len(windows_by_symbol) - (crit_count + warn_count)

    lines.append(f"- ✅ **OK**: {ok_count} symbols")
    lines.append(f"- 🟡 **WARN**: {warn_count} symbols with warnings")
    lines.append(f"- 🔴 **CRIT**: {crit_count} symbols with critical issues")
    lines.append("")

    if crit_count > 0:
        lines.append(
            "**⚠️ Action Required:** Critical violations detected. Review RECOMMENDATIONS.md for actionable steps.")
    elif warn_count > 0:
        lines.append(
            "**ℹ️ Attention:** Some warnings detected. Consider reviewing RECOMMENDATIONS.md.")
    else:
        lines.append(
            "**✅ All Clear:** No violations detected. System performing within thresholds.")

    # Write report
    report_path = out_dir / "POST_SOAK_ANALYSIS.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"[INFO] Analysis report written to: {report_path}")

    return crit_count, all_violations


def generate_recommendations_report(
    windows_by_symbol: Dict[str, List[Dict[str, Any]]],
    all_violations: List[Dict[str, Any]],
    thresholds: Dict[str, float],
    out_dir: Path
):
    """Generate RECOMMENDATIONS.md report."""
    lines = [
        "# Post-Soak Recommendations",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "Этот отчёт содержит конкретные рекомендации по улучшению метрик для каждого символа.",
        "",
        "---",
        ""
    ]

    for symbol in sorted(windows_by_symbol.keys()):
        windows = windows_by_symbol[symbol]

        # Extract metrics series
        metrics_series = {
            "edge_bps": [],
            "maker_taker_ratio": [],
            "p95_latency_ms": [],
            "risk_ratio": []
        }

        for window in windows:
            for metric_name in metrics_series.keys():
                value = window["metrics"].get(metric_name)
                metrics_series[metric_name].append(value)

        # Get violations for this symbol
        symbol_violations = [
            v for v in all_violations if v["symbol"] == symbol]

        # Generate recommendations
        recommendations = generate_recommendations(
            symbol, metrics_series, symbol_violations)

        lines.append(f"## {symbol}")
        lines.append("")

        for rec in recommendations:
            lines.append(f"{rec}")
            lines.append("")

        lines.append("---")
    lines.append("")

    # Write recommendations
    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / "RECOMMENDATIONS.md"
    rec_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"[INFO] Recommendations written to: {rec_path}")


def generate_violations_json(
    all_violations: List[Dict[str, Any]],
    out_dir: Path
):
    """Generate VIOLATIONS.json machine-readable report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    violations_path = out_dir / "VIOLATIONS.json"

    with open(violations_path, 'w', encoding='utf-8') as f:
        json.dump(all_violations, f, indent=2, ensure_ascii=False)

    print(f"[INFO] Violations JSON written to: {violations_path}")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Post-Soak Analyzer V2 - Trends, violations, recommendations")

    parser.add_argument(
        "--iter-glob",
        type=str,
        required=True,
        help="Glob pattern for ITER_SUMMARY files (e.g., 'artifacts/soak/latest/ITER_SUMMARY_*.json')"
    )
    parser.add_argument(
        "--min-windows",
        type=int,
        default=48,
        help="Minimum expected windows (default: 48)"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("reports/analysis"),
        help="Output directory for reports (default: reports/analysis)"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="*",
        help="Symbol filter (comma-separated or '*' for all, default: '*')"
    )
    parser.add_argument(
        "--time-buckets",
        type=int,
        default=10,
        help="Number of points for sparklines (default: 10)"
    )
    parser.add_argument(
        "--warn-edge",
        type=float,
        default=3.0,
        help="Warning threshold for edge_bps (default: 3.0)"
    )
    parser.add_argument(
        "--crit-edge",
        type=float,
        default=2.5,
        help="Critical threshold for edge_bps (default: 2.5)"
    )
    parser.add_argument(
        "--warn-maker",
        type=float,
        default=0.75,
        help="Warning threshold for maker_taker_ratio (default: 0.75)"
    )
    parser.add_argument(
        "--crit-maker",
        type=float,
        default=0.70,
        help="Critical threshold for maker_taker_ratio (default: 0.70)"
    )
    parser.add_argument(
        "--warn-lat",
        type=float,
        default=330,
        help="Warning threshold for p95_latency_ms (default: 330)"
    )
    parser.add_argument(
        "--crit-lat",
        type=float,
        default=350,
        help="Critical threshold for p95_latency_ms (default: 350)"
    )
    parser.add_argument(
        "--warn-risk",
        type=float,
        default=0.40,
        help="Warning threshold for risk_ratio (default: 0.40)"
    )
    parser.add_argument(
        "--crit-risk",
        type=float,
        default=0.40,
        help="Critical threshold for risk_ratio (default: 0.40)"
    )
    parser.add_argument(
        "--exit-on-crit",
        action="store_true",
        help="Exit with code 1 if critical violations found"
    )

    args = parser.parse_args()

    # Parse symbols filter
    symbols_filter = None
    if args.symbols != "*":
        symbols_filter = [s.strip() for s in args.symbols.split(",")]

    # Load windows
    print(f"[INFO] Loading windows from: {args.iter_glob}")
    windows_by_symbol = load_windows(args.iter_glob, symbols_filter)

    if not windows_by_symbol:
        print("[ERROR] No data loaded")
        return 1

    print(f"[INFO] Loaded {len(windows_by_symbol)} symbols")

    # Build thresholds dict
    thresholds = {
        "warn_edge": args.warn_edge,
        "crit_edge": args.crit_edge,
        "warn_maker": args.warn_maker,
        "crit_maker": args.crit_maker,
        "warn_lat": args.warn_lat,
        "crit_lat": args.crit_lat,
        "warn_risk": args.warn_risk,
        "crit_risk": args.crit_risk,
    }

    # Generate reports
    print(f"[INFO] Generating analysis reports in: {args.out_dir}")

    crit_count, all_violations = generate_analysis_report(
        windows_by_symbol,
        thresholds,
        args.min_windows,
        args.out_dir
    )

    generate_recommendations_report(
        windows_by_symbol,
        all_violations,
        thresholds,
        args.out_dir
    )

    generate_violations_json(
        all_violations,
        args.out_dir
    )

    # Summary
    print("")
    print("=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"Total symbols: {len(windows_by_symbol)}")
    print(f"Total violations: {len(all_violations)}")
    print(f"Critical violations: {crit_count}")
    print("")
    print(f"Reports generated:")
    print(f"  - {args.out_dir / 'POST_SOAK_ANALYSIS.md'}")
    print(f"  - {args.out_dir / 'RECOMMENDATIONS.md'}")
    print(f"  - {args.out_dir / 'VIOLATIONS.json'}")
    print("=" * 60)

    # Exit based on --exit-on-crit
    if args.exit_on_crit and crit_count > 0:
        print(
            f"\n[EXIT] Critical violations detected ({crit_count}), exiting with code 1")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

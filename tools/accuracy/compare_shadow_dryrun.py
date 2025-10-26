#!/usr/bin/env python3
"""
Compare Shadow vs Dry-Run KPI with MAPE and median delta metrics.

Exit codes:
  0 = PASS (all thresholds met)
  1 = FAIL (critical thresholds violated)
  2 = WARN (soft thresholds violated)
"""
import argparse
import glob
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# KPI to compare
KPIS = ["edge_bps", "maker_taker_ratio", "p95_latency_ms", "risk_ratio"]


def parse_iter_files(glob_pattern: str, max_age_min: Optional[int] = None) -> List[Dict]:
    """Parse ITER_SUMMARY_*.json files from glob pattern."""
    files = sorted(glob.glob(glob_pattern))
    if not files:
        logger.warning(f"No files matched pattern: {glob_pattern}")
        return []
    
    logger.info(f"Found {len(files)} files for pattern: {glob_pattern}")
    
    now = datetime.now(timezone.utc)
    iters = []
    
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Check age if max_age_min is specified
            if max_age_min is not None:
                ts_str = data.get("meta", {}).get("timestamp")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        age_min = (now - ts).total_seconds() / 60
                        if age_min > max_age_min:
                            logger.debug(f"Skipping {fpath}: too old ({age_min:.0f} min)")
                            continue
                    except (ValueError, AttributeError):
                        pass
            
            iters.append(data)
        except Exception as e:
            logger.warning(f"Failed to parse {fpath}: {e}")
    
    logger.info(f"Loaded {len(iters)} valid iterations (max_age_min={max_age_min})")
    return iters


def extract_kpi_by_symbol(iters: List[Dict], symbols: List[str]) -> Dict[str, Dict[str, List[float]]]:
    """
    Extract KPI values by symbol across all iterations.
    
    Returns: {symbol: {kpi: [values]}}
    """
    result = {sym: {kpi: [] for kpi in KPIS} for sym in symbols}
    
    for iteration in iters:
        for sym in symbols:
            sym_data = iteration.get(sym, {})
            if not sym_data:
                continue
            
            for kpi in KPIS:
                value = sym_data.get(kpi)
                if value is not None and isinstance(value, (int, float)):
                    result[sym][kpi].append(float(value))
    
    return result


def compute_mape(shadow_vals: List[float], dryrun_vals: List[float]) -> Optional[float]:
    """Compute Mean Absolute Percentage Error (MAPE)."""
    if not shadow_vals or not dryrun_vals:
        return None
    
    min_len = min(len(shadow_vals), len(dryrun_vals))
    if min_len == 0:
        return None
    
    # Align arrays (take last N values)
    shadow_aligned = shadow_vals[-min_len:]
    dryrun_aligned = dryrun_vals[-min_len:]
    
    errors = []
    for s, d in zip(shadow_aligned, dryrun_aligned):
        if abs(s) < 1e-9:  # Avoid division by zero
            continue
        error = abs((s - d) / s) * 100
        errors.append(error)
    
    if not errors:
        return None
    
    return sum(errors) / len(errors)


def compute_median_delta(shadow_vals: List[float], dryrun_vals: List[float]) -> Optional[float]:
    """Compute median absolute delta between shadow and dryrun."""
    if not shadow_vals or not dryrun_vals:
        return None
    
    min_len = min(len(shadow_vals), len(dryrun_vals))
    if min_len == 0:
        return None
    
    shadow_aligned = shadow_vals[-min_len:]
    dryrun_aligned = dryrun_vals[-min_len:]
    
    deltas = [abs(s - d) for s, d in zip(shadow_aligned, dryrun_aligned)]
    deltas_sorted = sorted(deltas)
    
    mid = len(deltas_sorted) // 2
    if len(deltas_sorted) % 2 == 0:
        return (deltas_sorted[mid - 1] + deltas_sorted[mid]) / 2
    else:
        return deltas_sorted[mid]


def compare_kpis(
    shadow_data: Dict[str, Dict[str, List[float]]],
    dryrun_data: Dict[str, Dict[str, List[float]]],
    mape_threshold: float,
    median_delta_threshold_bps: float
) -> Tuple[Dict, str]:
    """
    Compare Shadow vs Dry-Run KPIs.
    
    Returns: (results_dict, verdict: "PASS"/"WARN"/"FAIL")
    """
    results = {}
    has_fail = False
    has_warn = False
    
    all_symbols = set(shadow_data.keys()) | set(dryrun_data.keys())
    
    for sym in sorted(all_symbols):
        sym_results = {}
        shadow_sym = shadow_data.get(sym, {})
        dryrun_sym = dryrun_data.get(sym, {})
        
        for kpi in KPIS:
            shadow_vals = shadow_sym.get(kpi, [])
            dryrun_vals = dryrun_sym.get(kpi, [])
            
            mape = compute_mape(shadow_vals, dryrun_vals)
            median_delta = compute_median_delta(shadow_vals, dryrun_vals)
            
            # Determine status
            kpi_status = "OK"
            if mape is not None and mape > mape_threshold:
                kpi_status = "FAIL"
                has_fail = True
            elif median_delta is not None and median_delta > median_delta_threshold_bps:
                if kpi in ["edge_bps", "maker_taker_ratio"]:
                    # For edge and maker_taker, delta is in bps or ratio
                    kpi_status = "WARN"
                    has_warn = True
            
            sym_results[kpi] = {
                "mape_pct": round(mape, 2) if mape is not None else None,
                "median_delta": round(median_delta, 4) if median_delta is not None else None,
                "shadow_count": len(shadow_vals),
                "dryrun_count": len(dryrun_vals),
                "status": kpi_status
            }
        
        results[sym] = sym_results
    
    # Overall verdict
    if has_fail:
        verdict = "FAIL"
    elif has_warn:
        verdict = "WARN"
    else:
        verdict = "PASS"
    
    return results, verdict


def generate_markdown_report(
    results: Dict,
    verdict: str,
    mape_threshold: float,
    median_delta_threshold_bps: float,
    out_path: Path
) -> None:
    """Generate ACCURACY_REPORT.md."""
    lines = [
        "# Accuracy Gate: Shadow ↔ Dry-Run Comparison",
        "",
        f"**Verdict:** {verdict}",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Thresholds",
        "",
        f"- **MAPE threshold:** {mape_threshold * 100:.1f}%",
        f"- **Median Δ threshold (BPS):** {median_delta_threshold_bps:.2f}",
        "",
        "## Per-Symbol Comparison",
        ""
    ]
    
    for sym, kpis in sorted(results.items()):
        lines.append(f"### {sym}")
        lines.append("")
        lines.append("| KPI | MAPE (%) | Median Δ | Shadow N | Dryrun N | Status |")
        lines.append("|-----|----------|----------|----------|----------|--------|")
        
        for kpi, metrics in kpis.items():
            mape = metrics["mape_pct"]
            delta = metrics["median_delta"]
            shadow_n = metrics["shadow_count"]
            dryrun_n = metrics["dryrun_count"]
            status = metrics["status"]
            
            status_badge = {"OK": "✅", "WARN": "🟡", "FAIL": "🔴"}.get(status, "❓")
            
            mape_str = f"{mape:.2f}" if mape is not None else "n/a"
            delta_str = f"{delta:.4f}" if delta is not None else "n/a"
            
            lines.append(
                f"| {kpi} | {mape_str} | {delta_str} | {shadow_n} | {dryrun_n} | {status_badge} {status} |"
            )
        
        lines.append("")
    
    lines.extend([
        "## Summary",
        "",
        f"- **Verdict:** {verdict}",
        f"- **Symbols analyzed:** {len(results)}",
        "",
        "### Interpretation",
        "",
        "- **MAPE:** Mean Absolute Percentage Error - measures relative accuracy",
        "- **Median Δ:** Median absolute difference - measures absolute deviation",
        "- **✅ OK:** All thresholds met",
        "- **🟡 WARN:** Soft threshold violated (informational)",
        "- **🔴 FAIL:** Critical threshold violated (blocks PR)",
        ""
    ])
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Markdown report written to {out_path}")


def generate_json_summary(
    results: Dict,
    verdict: str,
    mape_threshold: float,
    median_delta_threshold_bps: float,
    out_path: Path
) -> None:
    """Generate ACCURACY_SUMMARY.json."""
    summary = {
        "verdict": verdict,
        "generated_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
        "thresholds": {
            "mape_pct": mape_threshold * 100,
            "median_delta_bps": median_delta_threshold_bps
        },
        "symbols": results,
        "meta": {
            "symbols_count": len(results),
            "fail_count": sum(
                1 for sym_kpis in results.values()
                for kpi_data in sym_kpis.values()
                if kpi_data["status"] == "FAIL"
            ),
            "warn_count": sum(
                1 for sym_kpis in results.values()
                for kpi_data in sym_kpis.values()
                if kpi_data["status"] == "WARN"
            )
        }
    }
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info(f"JSON summary written to {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Shadow vs Dry-Run KPI accuracy"
    )
    parser.add_argument(
        "--shadow",
        required=True,
        help='Shadow ITER_SUMMARY glob (e.g., "artifacts/shadow/latest/ITER_SUMMARY_*.json")'
    )
    parser.add_argument(
        "--dryrun",
        required=True,
        help='Dry-Run ITER_SUMMARY glob (e.g., "artifacts/dryrun/latest/ITER_SUMMARY_*.json")'
    )
    parser.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT",
        help="Comma-separated symbols to compare (default: BTCUSDT,ETHUSDT)"
    )
    parser.add_argument(
        "--min-windows",
        type=int,
        default=24,
        help="Minimum windows required for comparison (default: 24)"
    )
    parser.add_argument(
        "--max-age-min",
        type=int,
        default=90,
        help="Max age of data in minutes (default: 90)"
    )
    parser.add_argument(
        "--mape-threshold",
        type=float,
        default=0.15,
        help="MAPE threshold as fraction (default: 0.15 = 15%%)"
    )
    parser.add_argument(
        "--median-delta-threshold-bps",
        type=float,
        default=1.5,
        help="Median delta threshold in BPS (default: 1.5)"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("reports/analysis"),
        help="Output directory for reports (default: reports/analysis)"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("=" * 60)
    logger.info("Accuracy Gate: Shadow ↔ Dry-Run Comparison")
    logger.info("=" * 60)
    
    # Parse symbols
    symbols = [s.strip() for s in args.symbols.split(",")]
    logger.info(f"Symbols: {', '.join(symbols)}")
    logger.info(f"Min windows: {args.min_windows}")
    logger.info(f"Max age: {args.max_age_min} minutes")
    logger.info(f"MAPE threshold: {args.mape_threshold * 100:.1f}%")
    logger.info(f"Median Δ threshold: {args.median_delta_threshold_bps} BPS")
    logger.info("")
    
    # Load data
    logger.info("Loading Shadow data...")
    shadow_iters = parse_iter_files(args.shadow, args.max_age_min)
    
    logger.info("Loading Dry-Run data...")
    dryrun_iters = parse_iter_files(args.dryrun, args.max_age_min)
    
    if len(shadow_iters) < args.min_windows:
        logger.error(
            f"Insufficient Shadow windows: {len(shadow_iters)} < {args.min_windows}"
        )
        return 1
    
    if len(dryrun_iters) < args.min_windows:
        logger.error(
            f"Insufficient Dry-Run windows: {len(dryrun_iters)} < {args.min_windows}"
        )
        return 1
    
    # Extract KPIs
    logger.info("Extracting KPIs by symbol...")
    shadow_data = extract_kpi_by_symbol(shadow_iters, symbols)
    dryrun_data = extract_kpi_by_symbol(dryrun_iters, symbols)
    
    # Compare
    logger.info("Computing MAPE and median delta...")
    results, verdict = compare_kpis(
        shadow_data,
        dryrun_data,
        args.mape_threshold,
        args.median_delta_threshold_bps
    )
    
    logger.info("")
    logger.info(f"Verdict: {verdict}")
    logger.info("")
    
    # Generate reports
    md_path = args.out_dir / "ACCURACY_REPORT.md"
    json_path = args.out_dir / "ACCURACY_SUMMARY.json"
    
    generate_markdown_report(
        results, verdict, args.mape_threshold, args.median_delta_threshold_bps, md_path
    )
    generate_json_summary(
        results, verdict, args.mape_threshold, args.median_delta_threshold_bps, json_path
    )
    
    logger.info("=" * 60)
    logger.info(f"Accuracy Gate: {verdict}")
    logger.info("=" * 60)
    
    # Exit code
    if verdict == "PASS":
        return 0
    elif verdict == "WARN":
        return 2
    else:  # FAIL
        return 1


if __name__ == "__main__":
    sys.exit(main())


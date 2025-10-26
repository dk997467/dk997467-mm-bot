#!/usr/bin/env python3
"""
Sanity check for Accuracy Gate: validates edge cases and formatting.

Scenarios:
  1. Empty/Non-overlap: Non-matching symbols → WARN (expected)
  2. Max-Age filter: Old windows filtered out → WARN (expected)
  3. Formatting: Many symbols → table renders correctly
"""
import argparse
import json
import logging
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def create_mock_iter_file(path: Path, index: int, symbol_data: Dict, age_min: int = 0) -> None:
    """Create a mock ITER_SUMMARY file."""
    ts = datetime.now(timezone.utc) - timedelta(minutes=age_min)
    data = {
        "meta": {"timestamp": ts.isoformat()},
        **symbol_data
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def run_comparison(
    shadow_glob: str,
    dryrun_glob: str,
    symbols: str,
    min_windows: int,
    max_age_min: int,
    mape_threshold: float,
    median_delta_bps: float,
    report_dir: Path
) -> Tuple[int, str, Dict]:
    """
    Run accuracy comparison and return (exit_code, report_md, summary_json).
    """
    cmd = [
        sys.executable, "-m", "tools.accuracy.compare_shadow_dryrun",
        "--shadow", shadow_glob,
        "--dryrun", dryrun_glob,
        "--symbols", symbols,
        "--min-windows", str(min_windows),
        "--max-age-min", str(max_age_min),
        "--mape-threshold", str(mape_threshold),
        "--median-delta-threshold-bps", str(median_delta_bps),
        "--out-dir", str(report_dir),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    exit_code = result.returncode
    
    # Read generated reports
    report_md_path = report_dir / "ACCURACY_REPORT.md"
    summary_json_path = report_dir / "ACCURACY_SUMMARY.json"
    
    report_md = ""
    if report_md_path.exists():
        report_md = report_md_path.read_text(encoding="utf-8")
    
    summary_json = {}
    if summary_json_path.exists():
        summary_json = json.loads(summary_json_path.read_text(encoding="utf-8"))
    
    return exit_code, report_md, summary_json


def scenario_empty_nonoverlap(
    min_windows: int,
    max_age_min: int,
    mape_threshold: float,
    median_delta_bps: float,
    report_dir: Path
) -> Tuple[str, bool]:
    """
    Scenario 1: Non-overlapping symbols.
    
    Expected: WARN or PASS (no data to compare, should not FAIL).
    """
    logger.info("=" * 60)
    logger.info("Scenario 1: Empty/Non-overlapping symbols")
    logger.info("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Shadow: BTCUSDT
        shadow_dir = tmpdir_path / "shadow"
        shadow_dir.mkdir()
        for i in range(min_windows):
            create_mock_iter_file(
                shadow_dir / f"ITER_SUMMARY_{i:03d}.json",
                i,
                {"BTCUSDT": {"edge_bps": 3.5 + i * 0.01, "maker_taker_ratio": 0.85, "p95_latency_ms": 300, "risk_ratio": 0.35}}
            )
        
        # Dry-run: ETHUSDT (no overlap!)
        dryrun_dir = tmpdir_path / "dryrun"
        dryrun_dir.mkdir()
        for i in range(min_windows):
            create_mock_iter_file(
                dryrun_dir / f"ITER_SUMMARY_{i:03d}.json",
                i,
                {"ETHUSDT": {"edge_bps": 2.8 + i * 0.01, "maker_taker_ratio": 0.83, "p95_latency_ms": 320, "risk_ratio": 0.37}}
            )
        
        scenario_report_dir = report_dir / "sanity_empty"
        scenario_report_dir.mkdir(parents=True, exist_ok=True)
        
        exit_code, report_md, summary_json = run_comparison(
            str(shadow_dir / "ITER_SUMMARY_*.json"),
            str(dryrun_dir / "ITER_SUMMARY_*.json"),
            "BTCUSDT,ETHUSDT",
            min_windows,
            max_age_min,
            mape_threshold,
            median_delta_bps,
            scenario_report_dir
        )
        
        verdict = summary_json.get("verdict", "UNKNOWN")
        
        # Expected: WARN or PASS (no data means no error)
        passed = verdict in ["WARN", "PASS"]
        
        result = f"### Scenario 1: Empty/Non-overlapping Symbols\n\n"
        result += f"**Exit Code:** {exit_code} ({['PASS', 'FAIL', 'WARN'][exit_code] if exit_code in [0, 1, 2] else 'UNKNOWN'})\n"
        result += f"**Verdict:** {verdict}\n"
        result += f"**Expected:** WARN or PASS (no overlapping data)\n"
        result += f"**Status:** {'✅ PASS' if passed else '❌ FAIL'}\n\n"
        result += f"**Explanation:** Non-overlapping symbols means no data to compare. "
        result += f"This should result in WARN (informational) or PASS, never FAIL.\n\n"
        
        if summary_json:
            result += f"**Summary Stats:**\n"
            result += f"- Symbols: {summary_json.get('meta', {}).get('symbols_count', 0)}\n"
            result += f"- Fail count: {summary_json.get('meta', {}).get('fail_count', 0)}\n"
            result += f"- Warn count: {summary_json.get('meta', {}).get('warn_count', 0)}\n\n"
        
        return result, passed


def scenario_maxage_filter(
    min_windows: int,
    max_age_min: int,
    mape_threshold: float,
    median_delta_bps: float,
    report_dir: Path
) -> Tuple[str, bool]:
    """
    Scenario 2: Old windows filtered by max-age.
    
    Expected: WARN or exit 1 with "Insufficient windows" (acceptable).
    """
    logger.info("=" * 60)
    logger.info("Scenario 2: Max-Age filtering")
    logger.info("=" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Shadow: recent data
        shadow_dir = tmpdir_path / "shadow"
        shadow_dir.mkdir()
        for i in range(min_windows):
            create_mock_iter_file(
                shadow_dir / f"ITER_SUMMARY_{i:03d}.json",
                i,
                {"BTCUSDT": {"edge_bps": 3.5 + i * 0.01, "maker_taker_ratio": 0.85, "p95_latency_ms": 300, "risk_ratio": 0.35}},
                age_min=5  # Recent (5 min old)
            )
        
        # Dry-run: OLD data (should be filtered out)
        dryrun_dir = tmpdir_path / "dryrun"
        dryrun_dir.mkdir()
        for i in range(min_windows):
            create_mock_iter_file(
                dryrun_dir / f"ITER_SUMMARY_{i:03d}.json",
                i,
                {"BTCUSDT": {"edge_bps": 3.5 + i * 0.01, "maker_taker_ratio": 0.85, "p95_latency_ms": 300, "risk_ratio": 0.35}},
                age_min=max_age_min + 30  # OLD (filtered out)
            )
        
        scenario_report_dir = report_dir / "sanity_maxage"
        scenario_report_dir.mkdir(parents=True, exist_ok=True)
        
        exit_code, report_md, summary_json = run_comparison(
            str(shadow_dir / "ITER_SUMMARY_*.json"),
            str(dryrun_dir / "ITER_SUMMARY_*.json"),
            "BTCUSDT",
            min_windows,
            max_age_min,
            mape_threshold,
            median_delta_bps,
            scenario_report_dir
        )
        
        verdict = summary_json.get("verdict", "UNKNOWN")
        
        # Expected: exit 1 with "Insufficient windows" OR WARN
        passed = (exit_code == 1) or (verdict in ["WARN", "PASS"])
        
        result = f"### Scenario 2: Max-Age Filter\n\n"
        result += f"**Exit Code:** {exit_code} ({['PASS', 'FAIL', 'WARN'][exit_code] if exit_code in [0, 1, 2] else 'UNKNOWN'})\n"
        result += f"**Verdict:** {verdict if verdict != 'UNKNOWN' else 'N/A (insufficient windows)'}\n"
        result += f"**Expected:** Exit 1 (insufficient windows after filtering) or WARN\n"
        result += f"**Status:** {'✅ PASS' if passed else '❌ FAIL'}\n\n"
        result += f"**Explanation:** Old windows (age > {max_age_min} min) should be filtered out. "
        result += f"This results in insufficient data, which correctly causes exit 1 or WARN.\n\n"
        
        return result, passed


def scenario_formatting_table(
    min_windows: int,
    max_age_min: int,
    mape_threshold: float,
    median_delta_bps: float,
    report_dir: Path
) -> Tuple[str, bool]:
    """
    Scenario 3: Many symbols for formatting check.
    
    Expected: PASS, table renders correctly without breaking markdown.
    """
    logger.info("=" * 60)
    logger.info("Scenario 3: Formatting check (many symbols)")
    logger.info("=" * 60)
    
    # Create many symbols
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT", 
               "DOTUSDT", "MATICUSDT", "AVAXUSDT", "ATOMUSDT", "LINKUSDT"]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        
        # Shadow: all symbols
        shadow_dir = tmpdir_path / "shadow"
        shadow_dir.mkdir()
        for i in range(min_windows):
            symbol_data = {}
            for sym in symbols:
                symbol_data[sym] = {
                    "edge_bps": 3.5 + i * 0.01,
                    "maker_taker_ratio": 0.85 - i * 0.001,
                    "p95_latency_ms": 300 + i * 2,
                    "risk_ratio": 0.35 + i * 0.002
                }
            create_mock_iter_file(
                shadow_dir / f"ITER_SUMMARY_{i:03d}.json",
                i,
                symbol_data
            )
        
        # Dry-run: same symbols (perfect match for formatting test)
        dryrun_dir = tmpdir_path / "dryrun"
        dryrun_dir.mkdir()
        for i in range(min_windows):
            symbol_data = {}
            for sym in symbols:
                symbol_data[sym] = {
                    "edge_bps": 3.5 + i * 0.01,
                    "maker_taker_ratio": 0.85 - i * 0.001,
                    "p95_latency_ms": 300 + i * 2,
                    "risk_ratio": 0.35 + i * 0.002
                }
            create_mock_iter_file(
                dryrun_dir / f"ITER_SUMMARY_{i:03d}.json",
                i,
                symbol_data
            )
        
        scenario_report_dir = report_dir / "sanity_format"
        scenario_report_dir.mkdir(parents=True, exist_ok=True)
        
        exit_code, report_md, summary_json = run_comparison(
            str(shadow_dir / "ITER_SUMMARY_*.json"),
            str(dryrun_dir / "ITER_SUMMARY_*.json"),
            ",".join(symbols),
            min_windows,
            max_age_min,
            mape_threshold,
            median_delta_bps,
            scenario_report_dir
        )
        
        verdict = summary_json.get("verdict", "UNKNOWN")
        
        # Check table formatting
        table_ok = True
        if report_md:
            # Simple check: markdown table lines should not be excessively long
            lines = report_md.split("\n")
            for line in lines:
                if line.startswith("|") and len(line) > 300:
                    table_ok = False
                    break
        
        # Expected: PASS (perfect match), table renders OK
        passed = (verdict == "PASS") and table_ok
        
        result = f"### Scenario 3: Formatting Check (Many Symbols)\n\n"
        result += f"**Exit Code:** {exit_code} ({['PASS', 'FAIL', 'WARN'][exit_code] if exit_code in [0, 1, 2] else 'UNKNOWN'})\n"
        result += f"**Verdict:** {verdict}\n"
        result += f"**Symbols:** {len(symbols)} symbols\n"
        result += f"**Table Formatting:** {'✅ OK' if table_ok else '❌ BROKEN'}\n"
        result += f"**Expected:** PASS (perfect match), table renders correctly\n"
        result += f"**Status:** {'✅ PASS' if passed else '❌ FAIL'}\n\n"
        result += f"**Explanation:** With {len(symbols)} symbols, the markdown table should render "
        result += f"without breaking (no excessively long lines, proper column alignment).\n\n"
        
        if report_md and table_ok:
            # Extract sample table rows
            lines = [l for l in report_md.split("\n") if l.startswith("|")]
            if lines:
                result += f"**Table Preview (first 5 rows):**\n"
                result += "```\n"
                result += "\n".join(lines[:5])
                result += "\n```\n\n"
        
        return result, passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sanity check for Accuracy Gate: validates edge cases and formatting"
    )
    parser.add_argument("--shadow-glob", default="artifacts/shadow/latest/ITER_SUMMARY_*.json")
    parser.add_argument("--dryrun-glob", default="artifacts/dryrun/latest/ITER_SUMMARY_*.json")
    parser.add_argument("--min-windows", type=int, default=24)
    parser.add_argument("--max-age-min", type=int, default=90)
    parser.add_argument("--mape-threshold", type=float, default=0.15)
    parser.add_argument("--median-delta-bps", type=float, default=1.5)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--report-dir", type=Path, default=Path("reports/analysis"))
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any scenario fails")
    parser.add_argument("--verbose", action="store_true")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("=" * 60)
    logger.info("Accuracy Gate: Sanity Check")
    logger.info("=" * 60)
    logger.info(f"Min windows: {args.min_windows}")
    logger.info(f"Max age: {args.max_age_min} minutes")
    logger.info(f"MAPE threshold: {args.mape_threshold * 100:.1f}%")
    logger.info(f"Median Δ threshold: {args.median_delta_bps} BPS")
    logger.info(f"Strict mode: {args.strict}")
    logger.info("")
    
    args.report_dir.mkdir(parents=True, exist_ok=True)
    
    # Run scenarios
    results = []
    all_passed = True
    
    result1, passed1 = scenario_empty_nonoverlap(
        args.min_windows,
        args.max_age_min,
        args.mape_threshold,
        args.median_delta_bps,
        args.report_dir
    )
    results.append(result1)
    all_passed = all_passed and passed1
    
    result2, passed2 = scenario_maxage_filter(
        args.min_windows,
        args.max_age_min,
        args.mape_threshold,
        args.median_delta_bps,
        args.report_dir
    )
    results.append(result2)
    all_passed = all_passed and passed2
    
    result3, passed3 = scenario_formatting_table(
        args.min_windows,
        args.max_age_min,
        args.mape_threshold,
        args.median_delta_bps,
        args.report_dir
    )
    results.append(result3)
    all_passed = all_passed and passed3
    
    # Generate summary report
    report_lines = [
        "# Accuracy Gate: Sanity Check Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Overall Verdict:** {'✅ SANITY: PASS' if all_passed else '⚠️ SANITY: ATTENTION'}",
        "",
        "## Configuration",
        "",
        f"- Min windows: {args.min_windows}",
        f"- Max age: {args.max_age_min} minutes",
        f"- MAPE threshold: {args.mape_threshold * 100:.1f}%",
        f"- Median Δ threshold: {args.median_delta_bps} BPS",
        f"- Strict mode: {args.strict}",
        "",
        "## Scenarios",
        "",
    ]
    
    report_lines.extend(["".join(results)])
    
    report_lines.extend([
        "",
        "## Summary",
        "",
        f"- Scenario 1 (Empty/Non-overlap): {'✅ PASS' if passed1 else '❌ FAIL'}",
        f"- Scenario 2 (Max-Age filter): {'✅ PASS' if passed2 else '❌ FAIL'}",
        f"- Scenario 3 (Formatting): {'✅ PASS' if passed3 else '❌ FAIL'}",
        "",
        f"**Overall:** {'✅ All scenarios passed' if all_passed else '⚠️ Some scenarios need attention'}",
        "",
        "## Interpretation",
        "",
        "- **Scenario 1:** Non-overlapping symbols should result in WARN (no data to compare), not FAIL.",
        "- **Scenario 2:** Old data filtered by max-age should result in exit 1 (insufficient windows) or WARN.",
        "- **Scenario 3:** Many symbols should produce a well-formatted markdown table without breaking.",
        "",
        "## Artifacts",
        "",
        "- Scenario 1 reports: `reports/analysis/sanity_empty/`",
        "- Scenario 2 reports: `reports/analysis/sanity_maxage/`",
        "- Scenario 3 reports: `reports/analysis/sanity_format/`",
        ""
    ])
    
    report_path = args.report_dir / "ACCURACY_SANITY.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    logger.info(f"Sanity report written to {report_path}")
    
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Sanity Check: {'✅ PASS' if all_passed else '⚠️ ATTENTION'}")
    logger.info("=" * 60)
    
    if args.strict and not all_passed:
        logger.error("Strict mode: exiting with code 1")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())


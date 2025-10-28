#!/usr/bin/env python3
"""
Step 1: Baseline Shadow (Real Feed) + Auto-Tune

Runs shadow mode with real feed, auto-tunes parameters if thresholds not met,
and generates Go/No-Go decision report.

Usage:
    python -m tools.shadow.baseline_autotune \
        --exchange bybit \
        --symbols BTCUSDT ETHUSDT \
        --profile moderate \
        --iterations 48
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Fix Windows console encoding for Unicode characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')


# KPI Thresholds
KPI_THRESHOLDS = {
    "maker_taker_ratio": {"min": 0.83, "label": "maker_taker_ratio"},
    "net_bps": {"min": 2.5, "label": "net_bps"},
    "p95_latency_ms": {"max": 350, "label": "p95_latency_ms"},
    "risk_ratio": {"max": 0.40, "label": "risk_ratio"},
}

# Auto-tune presets (applied in order if baseline fails)
AUTOTUNE_PRESETS = [
    {"name": "Baseline", "touch_dwell_ms": 25, "min_lot": 0.001},
    {"name": "Attempt A", "touch_dwell_ms": 35, "min_lot": 0.001},
    {"name": "Attempt B", "touch_dwell_ms": 45, "min_lot": 0.005},
    {"name": "Attempt C", "touch_dwell_ms": 45, "min_lot": 0.010},
]


def run_shadow(
    exchange: str,
    symbols: List[str],
    profile: str,
    iterations: int,
    touch_dwell_ms: float,
    min_lot: float,
    require_volume: bool,
    mock: bool,
) -> bool:
    """
    Run shadow mode with given parameters.
    
    Returns:
        True if successful, False otherwise
    """
    print(f"\n{'=' * 80}")
    print(f"RUNNING SHADOW MODE")
    print(f"{'=' * 80}")
    print(f"  Exchange: {exchange}")
    print(f"  Symbols: {', '.join(symbols)}")
    print(f"  Profile: {profile}")
    print(f"  Iterations: {iterations}")
    print(f"  touch_dwell_ms: {touch_dwell_ms}")
    print(f"  min_lot: {min_lot}")
    print(f"  require_volume: {require_volume}")
    print(f"  mock: {mock}")
    print(f"{'=' * 80}\n")
    
    cmd = [
        sys.executable, "-m", "tools.shadow.run_shadow",
        "--exchange", exchange,
        "--symbols", *symbols,
        "--profile", profile,
        "--iterations", str(iterations),
        "--touch_dwell_ms", str(touch_dwell_ms),
        "--min_lot", str(min_lot),
    ]
    
    if require_volume:
        cmd.append("--require_volume")
    
    if mock:
        cmd.extend(["--source", "mock"])
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False, text=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Shadow run failed with exit code {e.returncode}")
        return False


def build_reports() -> bool:
    """Build shadow reports."""
    print(f"\n{'=' * 80}")
    print("BUILDING REPORTS")
    print(f"{'=' * 80}\n")
    
    cmd = [sys.executable, "-m", "tools.shadow.build_shadow_reports"]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False, text=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Report build failed with exit code {e.returncode}")
        return False


def audit_artifacts() -> Tuple[bool, Dict]:
    """
    Audit shadow artifacts.
    
    Returns:
        (passed, kpis) tuple where passed is True if all KPIs met thresholds
    """
    print(f"\n{'=' * 80}")
    print("AUDITING ARTIFACTS")
    print(f"{'=' * 80}\n")
    
    # Read audit summary
    summary_path = Path("artifacts/shadow/latest/reports/analysis/POST_SHADOW_AUDIT_SUMMARY.json")
    
    if not summary_path.exists():
        print(f"ERROR: Audit summary not found: {summary_path}")
        return False, {}
    
    with open(summary_path, 'r', encoding='utf-8') as f:
        summary = json.load(f)
    
    readiness = summary.get("readiness", {})
    passed = readiness.get("pass", False)
    kpis = summary.get("snapshot_kpis", {})
    
    print(f"Readiness: {'PASS' if passed else 'FAIL'}")
    print(f"KPIs: {kpis}")
    
    return passed, kpis


def compute_kpis_from_iter_summaries() -> Dict:
    """Compute average KPIs from ITER_SUMMARY files."""
    from statistics import mean
    
    iter_files = sorted(Path("artifacts/shadow/latest").glob("ITER_SUMMARY_*.json"))
    
    if not iter_files:
        return {}
    
    data = []
    for f in iter_files:
        with open(f, 'r', encoding='utf-8') as fp:
            d = json.load(fp)
            summary = d.get("summary", {})
            data.append(summary)
    
    if not data:
        return {}
    
    kpis = {
        "maker_taker_ratio": mean(d.get("maker_taker_ratio", 0) for d in data),
        "net_bps": mean(d.get("net_bps", 0) for d in data),
        "p95_latency_ms": mean(d.get("p95_latency_ms", 9999) for d in data),
        "risk_ratio": mean(d.get("risk_ratio", 1) for d in data),
        "iterations": len(data),
    }
    
    return kpis


def check_kpis(kpis: Dict) -> Tuple[bool, List[str]]:
    """
    Check if KPIs meet thresholds.
    
    Returns:
        (all_pass, failures) tuple
    """
    failures = []
    
    mk = kpis.get("maker_taker_ratio", 0)
    if mk < KPI_THRESHOLDS["maker_taker_ratio"]["min"]:
        failures.append(f"maker_taker_ratio: {mk:.3f} < {KPI_THRESHOLDS['maker_taker_ratio']['min']}")
    
    nb = kpis.get("net_bps", 0)
    if nb < KPI_THRESHOLDS["net_bps"]["min"]:
        failures.append(f"net_bps: {nb:.2f} < {KPI_THRESHOLDS['net_bps']['min']}")
    
    lt = kpis.get("p95_latency_ms", 9999)
    if lt > KPI_THRESHOLDS["p95_latency_ms"]["max"]:
        failures.append(f"p95_latency_ms: {lt:.1f} > {KPI_THRESHOLDS['p95_latency_ms']['max']}")
    
    rr = kpis.get("risk_ratio", 1)
    if rr > KPI_THRESHOLDS["risk_ratio"]["max"]:
        failures.append(f"risk_ratio: {rr:.3f} > {KPI_THRESHOLDS['risk_ratio']['max']}")
    
    return len(failures) == 0, failures


def generate_summary_report(
    attempts: List[Dict],
    final_kpis: Dict,
    go: bool,
    failures: List[str],
) -> None:
    """Generate Step 1 baseline summary report."""
    output_path = Path("reports/analysis/STEP1_BASELINE_SUMMARY.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    lines = [
        "# STEP 1 — Baseline Shadow (Real Feed) + Auto-Tune",
        "",
        f"**Timestamp:** {timestamp}  ",
        f"**Iterations:** {final_kpis.get('iterations', 0)} windows  ",
        f"**Exchange:** bybit  ",
        f"**Symbols:** BTCUSDT, ETHUSDT  ",
        f"**Profile:** moderate  ",
        "",
        "---",
        "",
        "## KPI Summary (Averages)",
        "",
        "| Metric | Target | Actual | Status |",
        "|--------|--------|--------|--------|",
        f"| maker_taker_ratio | ≥ 0.83 | {final_kpis.get('maker_taker_ratio', 0):.3f} | {'✅' if final_kpis.get('maker_taker_ratio', 0) >= 0.83 else '❌'} |",
        f"| net_bps | ≥ 2.5 | {final_kpis.get('net_bps', 0):.2f} | {'✅' if final_kpis.get('net_bps', 0) >= 2.5 else '❌'} |",
        f"| p95_latency_ms | ≤ 350 | {final_kpis.get('p95_latency_ms', 9999):.1f} | {'✅' if final_kpis.get('p95_latency_ms', 9999) <= 350 else '❌'} |",
        f"| risk_ratio | ≤ 0.40 | {final_kpis.get('risk_ratio', 1):.3f} | {'✅' if final_kpis.get('risk_ratio', 1) <= 0.40 else '❌'} |",
        "",
        "---",
        "",
        "## Auto-Tune Attempts",
        "",
    ]
    
    for i, attempt in enumerate(attempts):
        lines.append(f"### Attempt {i + 1}: {attempt['name']}")
        lines.append("")
        lines.append(f"- touch_dwell_ms: {attempt['touch_dwell_ms']}")
        lines.append(f"- min_lot: {attempt['min_lot']}")
        lines.append(f"- Result: {attempt['result']}")
        
        if attempt.get('kpis'):
            kpis = attempt['kpis']
            lines.append(f"- maker_taker: {kpis.get('maker_taker_ratio', 0):.3f}")
            lines.append(f"- net_bps: {kpis.get('net_bps', 0):.2f}")
            lines.append(f"- latency: {kpis.get('p95_latency_ms', 9999):.1f}ms")
            lines.append(f"- risk: {kpis.get('risk_ratio', 1):.3f}")
        
        lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append("## Decision")
    lines.append("")
    
    if go:
        lines.append("### ✅ **GO**")
        lines.append("")
        lines.append("All KPI thresholds met. Shadow Mode baseline established.")
        lines.append("")
        lines.append("**Next Step:** Proceed to Redis Integration (Step 2)")
    else:
        lines.append("### ❌ **NO-GO**")
        lines.append("")
        lines.append("KPI thresholds not met:")
        lines.append("")
        for failure in failures:
            lines.append(f"- {failure}")
        lines.append("")
        lines.append("**Recommendations:**")
        lines.append("1. Review market conditions (volatility, liquidity)")
        lines.append("2. Try different symbols (e.g., SOLUSDT, AVAXUSDT)")
        lines.append("3. Increase iterations (e.g., 96 windows)")
        lines.append("4. Use Redis integration for prod-identical feed (Step 3)")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"**Generated:** {timestamp}  ")
    lines.append(f"**Report Path:** `{output_path}`  ")
    
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    
    print(f"\n{'=' * 80}")
    print("SUMMARY REPORT GENERATED")
    print(f"{'=' * 80}\n")
    print(output_path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="Step 1: Baseline Shadow (Real Feed) + Auto-Tune"
    )
    parser.add_argument(
        "--exchange",
        default="bybit",
        help="Exchange (default: bybit)"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        help="Symbols to monitor (default: BTCUSDT ETHUSDT)"
    )
    parser.add_argument(
        "--profile",
        default="moderate",
        choices=["moderate", "aggressive"],
        help="Trading profile (default: moderate)"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=48,
        help="Number of iterations (default: 48)"
    )
    parser.add_argument(
        "--require_volume",
        action="store_true",
        default=True,
        help="Require volume check (default: True)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock data (default: False, use real feed)"
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("STEP 1: BASELINE SHADOW (REAL FEED) + AUTO-TUNE")
    print("=" * 80)
    print(f"Exchange: {args.exchange}")
    print(f"Symbols: {', '.join(args.symbols)}")
    print(f"Profile: {args.profile}")
    print(f"Iterations: {args.iterations}")
    print(f"Mock mode: {args.mock}")
    print("=" * 80)
    print()
    
    attempts = []
    final_kpis = {}
    go = False
    failures = []
    
    for preset in AUTOTUNE_PRESETS:
        print(f"\n{'=' * 80}")
        print(f"TRYING PRESET: {preset['name']}")
        print(f"{'=' * 80}\n")
        
        # Run shadow
        success = run_shadow(
            exchange=args.exchange,
            symbols=args.symbols,
            profile=args.profile,
            iterations=args.iterations,
            touch_dwell_ms=preset["touch_dwell_ms"],
            min_lot=preset["min_lot"],
            require_volume=args.require_volume,
            mock=args.mock,
        )
        
        if not success:
            attempts.append({
                "name": preset["name"],
                "touch_dwell_ms": preset["touch_dwell_ms"],
                "min_lot": preset["min_lot"],
                "result": "FAILED (run error)",
                "kpis": None,
            })
            continue
        
        # Build reports
        success = build_reports()
        if not success:
            attempts.append({
                "name": preset["name"],
                "touch_dwell_ms": preset["touch_dwell_ms"],
                "min_lot": preset["min_lot"],
                "result": "FAILED (report error)",
                "kpis": None,
            })
            continue
        
        # Compute KPIs
        kpis = compute_kpis_from_iter_summaries()
        final_kpis = kpis
        
        # Check thresholds
        passed, failures = check_kpis(kpis)
        
        attempts.append({
            "name": preset["name"],
            "touch_dwell_ms": preset["touch_dwell_ms"],
            "min_lot": preset["min_lot"],
            "result": "PASS" if passed else "FAIL",
            "kpis": kpis,
        })
        
        if passed:
            go = True
            print(f"\n{'=' * 80}")
            print(f"✅ SUCCESS: {preset['name']} passed all KPI thresholds!")
            print(f"{'=' * 80}\n")
            break
        else:
            print(f"\n{'=' * 80}")
            print(f"❌ {preset['name']} failed:")
            for failure in failures:
                print(f"   - {failure}")
            print(f"{'=' * 80}\n")
    
    # Generate summary report
    generate_summary_report(attempts, final_kpis, go, failures)
    
    # Exit code
    if go:
        print("\n✅ STEP 1 COMPLETE: GO\n")
        sys.exit(0)
    else:
        print("\n❌ STEP 1 COMPLETE: NO-GO\n")
        sys.exit(1)


if __name__ == "__main__":
    main()


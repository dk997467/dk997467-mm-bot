#!/usr/bin/env python3
"""
Artifact Auditor for Soak Tests

Analyzes soak test artifacts from artifacts/soak/latest/ and produces:
- Console report with KPI summary
- Markdown report with trends and recommendations
- JSON summary with all computed metrics
- CSV table with per-iteration data

Usage:
    python -m tools.soak.audit_artifacts
    python -m tools.soak.audit_artifacts --base artifacts/soak/latest
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# UTF-8 safe I/O for cross-platform compatibility
from tools.common.utf8io import ensure_utf8_stdio, puts, sym

# Ensure UTF-8 output on all platforms
ensure_utf8_stdio()

# Try pandas, fallback to manual tabulation
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    puts("[WARN] pandas not available; using manual tabulation", file=sys.stderr)

# Try matplotlib for plots
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


# ==============================================================================
# CONFIGURATION
# ==============================================================================

READINESS_THRESHOLDS = {
    "maker_taker_ratio": (">=", 0.83),
    "net_bps": (">=", 2.9),
    "p95_latency_ms": ("<=", 330),
    "risk_ratio": ("<=", 0.40),
}

STEADY_START_ITER = 7  # Iterations >= 7 are considered STEADY


# ==============================================================================
# UTILITIES
# ==============================================================================

def safe_float(val: Any, default: float = float('nan')) -> float:
    """Safely convert to float."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def extract_iter_index(filename: str) -> Optional[int]:
    """Extract iteration index from ITER_SUMMARY_<N>.json."""
    match = re.search(r'ITER_SUMMARY_(\d+)\.json', filename)
    return int(match.group(1)) if match else None


def robust_kpi_extract(data: dict, iter_idx: int) -> dict:
    """
    Extract KPIs from ITER_SUMMARY JSON with multiple fallback paths.
    
    Returns dict with keys:
        iter, net_bps, risk_ratio, slippage_p95, adverse_p95,
        latency_p95_ms, maker_taker_ratio
    """
    summary = data.get("summary", {})
    
    # net_bps
    net_bps = safe_float(
        summary.get("net_bps") or summary.get("net") or summary.get("edge_bps")
    )
    
    # risk_ratio
    risk_val = summary.get("risk_ratio") or summary.get("risk")
    if risk_val is None:
        risk_percent = summary.get("risk_percent")
        if risk_percent is not None:
            risk_val = safe_float(risk_percent) / 100.0
    risk_ratio = safe_float(risk_val)
    
    # slippage_p95
    slippage_p95 = safe_float(
        summary.get("slippage_bps_p95") or summary.get("sl_p95") or summary.get("slippage_p95")
    )
    
    # adverse_p95
    adverse_p95 = safe_float(
        summary.get("adverse_bps_p95") or summary.get("adv_p95") or summary.get("adverse_p95")
    )
    
    # latency_p95_ms
    latency_p95_ms = safe_float(
        summary.get("p95_latency_ms") or summary.get("latency_p95_ms") or 
        summary.get("p95") or summary.get("latency_p95")
    )
    
    # maker_taker_ratio
    mt_ratio = summary.get("maker_taker_ratio") or summary.get("maker_ratio")
    if mt_ratio is None:
        # Try to compute from counts
        maker = safe_float(summary.get("maker_count"))
        taker = safe_float(summary.get("taker_count"))
        if not (pd.isna if HAS_PANDAS else lambda x: x != x)(maker) and \
           not (pd.isna if HAS_PANDAS else lambda x: x != x)(taker) and \
           (maker + taker) > 0:
            mt_ratio = maker / (maker + taker)
    maker_taker_ratio = safe_float(mt_ratio)
    
    return {
        "iter": iter_idx,
        "net_bps": net_bps,
        "risk_ratio": risk_ratio,
        "slippage_p95": slippage_p95,
        "adverse_p95": adverse_p95,
        "latency_p95_ms": latency_p95_ms,
        "maker_taker_ratio": maker_taker_ratio,
    }


def compute_stats(values: List[float]) -> dict:
    """Compute min/max/median from list of floats (ignoring NaN)."""
    if HAS_PANDAS:
        s = pd.Series(values).dropna()
        if len(s) == 0:
            return {"min": float('nan'), "max": float('nan'), "median": float('nan')}
        return {
            "min": float(s.min()),
            "max": float(s.max()),
            "median": float(s.median()),
        }
    else:
        clean = [v for v in values if v == v]  # Filter NaN
        if not clean:
            return {"min": float('nan'), "max": float('nan'), "median": float('nan')}
        clean_sorted = sorted(clean)
        n = len(clean_sorted)
        median = clean_sorted[n // 2] if n % 2 == 1 else (clean_sorted[n // 2 - 1] + clean_sorted[n // 2]) / 2
        return {
            "min": min(clean),
            "max": max(clean),
            "median": median,
        }


def check_readiness(snapshot: dict, window_name: str = "last-8") -> Tuple[bool, List[str]]:
    """
    Check readiness against thresholds.
    
    Returns (all_pass, list_of_failures).
    """
    failures = []
    
    for metric, (op, threshold) in READINESS_THRESHOLDS.items():
        actual = snapshot.get(metric, float('nan'))
        
        if actual != actual:  # NaN check
            failures.append(f"{metric}: missing (expected {op} {threshold})")
            continue
        
        passed = False
        if op == ">=":
            passed = actual >= threshold
        elif op == "<=":
            passed = actual <= threshold
        
        if not passed:
            failures.append(f"{metric}: {actual:.3f} (expected {op} {threshold})")
    
    return (len(failures) == 0, failures)


# ==============================================================================
# MAIN ANALYSIS
# ==============================================================================

def audit_artifacts(base_dir: str = "artifacts/soak/latest", generate_plots: bool = False) -> dict:
    """
    Main audit function.
    
    Args:
        base_dir: Base directory for soak artifacts
        generate_plots: Generate PNG plots if matplotlib available
    
    Returns dict with analysis results.
    """
    base_path = Path(base_dir)
    
    print("=" * 80)
    print(f"SOAK ARTIFACT AUDIT: {base_dir}")
    print("=" * 80)
    print()
    
    # ----- 1. Verify folder structure -----
    print("[1/11] Verifying folder structure...")
    if not base_path.exists():
        puts(f"{sym('fail')} ERROR: Base directory not found: {base_dir}")
        sys.exit(1)
    
    all_files = sorted(base_path.rglob("*"))
    file_inventory = []
    for f in all_files[:120]:  # Limit to 120 for readability
        if f.is_file():
            size_kb = f.stat().st_size / 1024
            file_inventory.append((f.relative_to(base_path), f"{size_kb:.1f} KB"))
    
    puts(f"{sym('ok')} Base directory exists: {base_path.absolute()}")
    print(f"  Files found: {len(file_inventory)} (showing first 120)")
    for name, size in file_inventory[:10]:
        print(f"    - {name}: {size}")
    if len(file_inventory) > 10:
        print(f"    ... and {len(file_inventory) - 10} more")
    print()
    
    # Check key files
    snapshot_path = base_path / "reports/analysis/POST_SOAK_SNAPSHOT.json"
    tuning_path = base_path / "TUNING_REPORT.json"
    delta_md_path = base_path / "DELTA_VERIFY_REPORT.md"
    warmup_prom_path = base_path / "reports/analysis/warmup_metrics.prom"
    
    files_present = {
        "POST_SOAK_SNAPSHOT.json": snapshot_path.exists(),
        "TUNING_REPORT.json": tuning_path.exists(),
        "DELTA_VERIFY_REPORT.md": delta_md_path.exists(),
        "warmup_metrics.prom": warmup_prom_path.exists(),
    }
    
    print("Key files:")
    for fname, exists in files_present.items():
        status = f"{sym('ok')}" if exists else f"{sym('fail')} (missing)"
        print(f"  {status} {fname}")
    print()
    
    # ----- 2. Load ITER_SUMMARY files -----
    print("[2/11] Loading ITER_SUMMARY files...")
    iter_files = sorted(base_path.glob("ITER_SUMMARY_*.json"))
    
    if len(iter_files) < 16:
        puts(f"{sym('warn')} WARNING: Only {len(iter_files)} ITER_SUMMARY files found (expected >= 16)")
    else:
        puts(f"{sym('ok')} Found {len(iter_files)} ITER_SUMMARY files")
    
    iter_data = []
    for iter_file in iter_files:
        try:
            with open(iter_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            iter_idx = data.get("iteration") or extract_iter_index(iter_file.name)
            if iter_idx is None:
                puts(f"  {sym('warn')} WARNING: Cannot extract iteration index from {iter_file.name}")
                continue
            
            kpi = robust_kpi_extract(data, iter_idx)
            iter_data.append(kpi)
        except Exception as e:
            puts(f"  {sym('fail')} ERROR loading {iter_file.name}: {e}")
    
    if not iter_data:
        puts(f"{sym('fail')} FATAL: No ITER_SUMMARY data loaded")
        sys.exit(1)
    
    # Sort by iteration
    iter_data.sort(key=lambda x: x["iter"])
    puts(f"{sym('ok')} Loaded {len(iter_data)} iterations")
    print()
    
    # Build DataFrame
    if HAS_PANDAS:
        df = pd.DataFrame(iter_data)
    else:
        df = iter_data  # Keep as list of dicts
    
    # ----- 3. Compute trend stats -----
    print("[3/11] Computing trend statistics...")
    
    if HAS_PANDAS:
        df_steady = df[df["iter"] >= STEADY_START_ITER]
        max_iter = df["iter"].max()
        last_8_start = max(1, max_iter - 7)
        df_last8 = df[df["iter"] >= last_8_start]
    else:
        df_steady = [row for row in iter_data if row["iter"] >= STEADY_START_ITER]
        max_iter = max(row["iter"] for row in iter_data)
        last_8_start = max(1, max_iter - 7)
        df_last8 = [row for row in iter_data if row["iter"] >= last_8_start]
    
    kpi_columns = ["net_bps", "risk_ratio", "latency_p95_ms", "maker_taker_ratio"]
    trend_stats = {}
    
    for col in kpi_columns:
        if HAS_PANDAS:
            overall = compute_stats(df[col].tolist())
            steady = compute_stats(df_steady[col].tolist())
            last8 = compute_stats(df_last8[col].tolist())
        else:
            overall = compute_stats([row[col] for row in iter_data])
            steady = compute_stats([row[col] for row in df_steady])
            last8 = compute_stats([row[col] for row in df_last8])
        
        trend_stats[col] = {
            "overall": overall,
            "steady": steady,
            "last8": last8,
        }
    
    print("Trend Statistics:")
    print(f"{'Metric':<20} {'Window':<10} {'Min':>8} {'Max':>8} {'Median':>8}")
    print("-" * 60)
    for col in kpi_columns:
        for window in ["overall", "steady", "last8"]:
            stats = trend_stats[col][window]
            print(f"{col:<20} {window:<10} {stats['min']:>8.2f} {stats['max']:>8.2f} {stats['median']:>8.2f}")
    print()
    
    # ----- 4. Build/Load POST_SOAK_SNAPSHOT -----
    print("[4/11] Loading/deriving POST_SOAK_SNAPSHOT...")
    
    if snapshot_path.exists():
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            snapshot = json.load(f)
        puts(f"{sym('ok')} Loaded existing POST_SOAK_SNAPSHOT.json")
        
        # Extract last-8 KPIs (may be in different structures)
        kpi_last8 = snapshot.get("kpi_last_n", {}) or snapshot.get("last8", {}) or snapshot
        snapshot_kpis = {
            "maker_taker_ratio": kpi_last8.get("maker_taker_ratio", {}).get("median", float('nan')),
            "net_bps": kpi_last8.get("net_bps", {}).get("median", float('nan')),
            "p95_latency_ms": kpi_last8.get("p95_latency_ms", {}).get("max", float('nan')),
            "risk_ratio": kpi_last8.get("risk_ratio", {}).get("median", float('nan')),
        }
    else:
        puts(f"{sym('warn')} POST_SOAK_SNAPSHOT.json not found; deriving from last-8 window")
        snapshot_kpis = {
            "maker_taker_ratio": trend_stats["maker_taker_ratio"]["last8"]["median"],
            "net_bps": trend_stats["net_bps"]["last8"]["median"],
            "p95_latency_ms": trend_stats["latency_p95_ms"]["last8"]["median"],
            "risk_ratio": trend_stats["risk_ratio"]["last8"]["median"],
        }
        snapshot = {"kpi_last_n": snapshot_kpis, "derived": True}
    
    print("Snapshot KPIs (last-8 window):")
    for k, v in snapshot_kpis.items():
        print(f"  {k}: {v:.3f}")
    print()
    
    # ----- 5. Readiness gate check -----
    print("[5/11] Readiness Gate Check (last-8 window)...")
    
    all_pass, failures = check_readiness(snapshot_kpis, "last-8")
    
    print(f"{'Metric':<20} {'Target':<15} {'Actual':>10} {'Status':>10}")
    print("-" * 60)
    for metric, (op, threshold) in READINESS_THRESHOLDS.items():
        actual = snapshot_kpis.get(metric, float('nan'))
        target_str = f"{op} {threshold}"
        
        if actual != actual:
            status = "MISSING"
        else:
            passed = (actual >= threshold) if op == ">=" else (actual <= threshold)
            status = f"{sym('ok')} PASS" if passed else f"{sym('fail')} FAIL"
        
        print(f"{metric:<20} {target_str:<15} {actual:>10.3f} {status:>10}")
    
    print()
    if all_pass:
        puts(f"{sym('ok')} READINESS: OK (all KPIs within thresholds)")
    else:
        puts(f"{sym('fail')} READINESS: HOLD")
        for failure in failures:
            print(f"  - {failure}")
    print()
    
    # ----- 6. Analyze TUNING_REPORT -----
    print("[6/11] Analyzing TUNING_REPORT.json...")
    
    tuning_summary = {"found": False}
    if tuning_path.exists():
        try:
            with open(tuning_path, 'r', encoding='utf-8') as f:
                tuning = json.load(f)
            
            tuning_summary["found"] = True
            
            # Aggregate guard skip reasons
            skip_reasons = Counter()
            proposed_count = 0
            applied_count = 0
            
            for iter_key, iter_data in tuning.items():
                if not isinstance(iter_data, dict):
                    continue
                
                guards = iter_data.get("guards", {})
                for guard_name, guard_data in guards.items():
                    if isinstance(guard_data, dict):
                        skip_reason = guard_data.get("skip_reason")
                        if skip_reason:
                            skip_reasons[skip_reason] += 1
                
                deltas = iter_data.get("deltas", {})
                for key, delta_info in deltas.items():
                    if isinstance(delta_info, dict):
                        if delta_info.get("proposed"):
                            proposed_count += 1
                        if delta_info.get("applied"):
                            applied_count += 1
            
            tuning_summary["skip_reasons"] = dict(skip_reasons)
            tuning_summary["proposed_total"] = proposed_count
            tuning_summary["applied_total"] = applied_count
            
            puts(f"{sym('ok')} TUNING_REPORT.json found")
            print(f"  Deltas: {applied_count}/{proposed_count} applied")
            
            if skip_reasons:
                print("  Guard skip reasons:")
                for reason, count in skip_reasons.most_common(5):
                    print(f"    - {reason}: {count}")
        except Exception as e:
            puts(f"  {sym('fail')} ERROR parsing TUNING_REPORT: {e}")
            tuning_summary["error"] = str(e)
    else:
        puts(f"{sym('fail')} TUNING_REPORT.json not found")
    print()
    
    # ----- 7. Parse DELTA_VERIFY_REPORT -----
    print("[7/11] Parsing DELTA_VERIFY_REPORT.md...")
    
    delta_verify_summary = {"found": False}
    if delta_md_path.exists():
        try:
            with open(delta_md_path, 'r', encoding='utf-8') as f:
                delta_md = f.read()
            
            delta_verify_summary["found"] = True
            
            # Extract counts from "Full applications: X/Y (Z%)"
            full_match = re.search(r'Full applications:\s*(\d+)/(\d+)\s*\(([\d\.]+)%\)', delta_md)
            if full_match:
                full_applied = int(full_match.group(1))
                full_total = int(full_match.group(2))
                full_pct = float(full_match.group(3))
                delta_verify_summary["full_applied"] = full_applied
                delta_verify_summary["full_total"] = full_total
                delta_verify_summary["full_pct"] = full_pct
                
                puts(f"{sym('ok')} DELTA_VERIFY_REPORT.md found")
                print(f"  Full applications: {full_applied}/{full_total} ({full_pct}%)")
            else:
                print("✓ DELTA_VERIFY_REPORT.md found (couldn't parse stats)")
        except Exception as e:
            puts(f"  {sym('fail')} ERROR parsing DELTA_VERIFY_REPORT: {e}")
            delta_verify_summary["error"] = str(e)
    else:
        puts(f"{sym('fail')} DELTA_VERIFY_REPORT.md not found")
    print()
    
    # ----- 8. Parse warmup_metrics.prom -----
    print("[8/11] Parsing warmup_metrics.prom...")
    
    warmup_summary = {"found": False}
    if warmup_prom_path.exists():
        try:
            with open(warmup_prom_path, 'r', encoding='utf-8') as f:
                prom_text = f.read()
            
            warmup_summary["found"] = True
            
            # Extract key metrics
            error_match = re.search(r'exporter_error\s+(\d+)', prom_text)
            if error_match:
                warmup_summary["exporter_error"] = int(error_match.group(1))
            
            guard_triggers = {}
            for match in re.finditer(r'guard_triggers_total\{type="([^"]+)"\}\s+(\d+)', prom_text):
                guard_type = match.group(1)
                count = int(match.group(2))
                guard_triggers[guard_type] = count
            
            warmup_summary["guard_triggers"] = guard_triggers
            
            puts(f"{sym('ok')} warmup_metrics.prom found")
            if warmup_summary.get("exporter_error"):
                print(f"  exporter_error: {warmup_summary['exporter_error']}")
            if guard_triggers:
                print("  Guard triggers:")
                for gtype, count in sorted(guard_triggers.items()):
                    print(f"    - {gtype}: {count}")
        except Exception as e:
            puts(f"  {sym('fail')} ERROR parsing warmup_metrics: {e}")
            warmup_summary["error"] = str(e)
    else:
        puts(f"{sym('fail')} warmup_metrics.prom not found")
    print()
    
    # ----- 9. Recommendations -----
    print("[9/11] Generating recommendations...")
    
    recommendations = []
    
    # Check maker_taker_ratio
    mt_last8 = snapshot_kpis.get("maker_taker_ratio", float('nan'))
    if mt_last8 < 0.83 and not (mt_last8 != mt_last8):
        adv_steady_median = trend_stats.get("net_bps", {}).get("steady", {}).get("median", float('nan'))
        
        rec = f"{sym('warn')} Maker/taker ratio below target (last-8: {mt_last8:.3f} < 0.83):"
        recommendations.append(rec)
        recommendations.append("  • Increase maker share:")
        recommendations.append("    - Nudge `quoting.base_spread_bps_delta` slightly higher")
        recommendations.append("    - Keep `risk.base_spread_bps_delta` conservative")
        recommendations.append("    - Reduce `taker_rescue.rescue_max_ratio`")
        recommendations.append("    - Raise `taker_rescue.min_edge_bps`")
        
        if adv_steady_median < 3.0 and not (adv_steady_median != adv_steady_median):
            recommendations.append("    - Consider relaxing `impact_cap_ratio` and `max_delta_ratio` (adverse_p95 STEADY is low: {:.2f})".format(adv_steady_median))
        
        recommendations.append("    - Monitor `min_interval_ms` and `replace_rate_per_min` to protect latency")
    
    # Check other KPIs
    for metric, (op, threshold) in READINESS_THRESHOLDS.items():
        actual = snapshot_kpis.get(metric, float('nan'))
        if actual == actual:  # Not NaN
            if op == ">=" and actual < threshold:
                recommendations.append(f"{sym('warn')} {metric} below target: {actual:.3f} < {threshold}")
            elif op == "<=" and actual > threshold:
                recommendations.append(f"{sym('warn')} {metric} above target: {actual:.3f} > {threshold}")
    
    if not recommendations:
        recommendations.append(f"{sym('ok')} All KPIs within target ranges; no immediate action needed")
    
    print("Recommendations:")
    for rec in recommendations:
        print(f"  {rec}")
    print()
    
    # ----- 10. Create Markdown report -----
    print("[10/11] Creating Markdown report...")
    
    out_dir = base_path / "reports/analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    out_md_path = out_dir / "POST_SOAK_AUDIT_SUMMARY.md"
    out_json_path = out_dir / "POST_SOAK_AUDIT_SUMMARY.json"
    out_csv_path = out_dir / "POST_SOAK_ITER_TABLE.csv"
    
    # Save CSV
    if HAS_PANDAS:
        df.to_csv(out_csv_path, index=False)
    else:
        with open(out_csv_path, 'w', encoding='utf-8') as f:
            if iter_data:
                headers = list(iter_data[0].keys())
                f.write(",".join(headers) + "\n")
                for row in iter_data:
                    f.write(",".join(str(row.get(h, "")) for h in headers) + "\n")
    
    puts(f"{sym('ok')} Saved CSV: {out_csv_path}")
    
    # Create Markdown
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    md_lines = [
        f"# Post-Soak Audit Summary",
        f"",
        f"**Generated:** {timestamp}  ",
        f"**Base Directory:** `{base_dir}`  ",
        f"**Iterations:** {len(iter_data)} (max iter: {max_iter})  ",
        f"**STEADY Window:** iter >= {STEADY_START_ITER}  ",
        f"**Last-8 Window:** iter >= {last_8_start}  ",
        f"",
        f"---",
        f"",
        f"## File Inventory",
        f"",
    ]
    
    for fname, exists in files_present.items():
        status = f"{sym('ok')}" if exists else f"{sym('fail')} (missing)"
        md_lines.append(f"- {status} `{fname}`")
    
    md_lines.extend([
        f"",
        f"---",
        f"",
        f"## Readiness Gate (last-8 window)",
        f"",
        f"| Metric | Target | Actual | Status |",
        f"|--------|--------|--------|--------|",
    ])
    
    for metric, (op, threshold) in READINESS_THRESHOLDS.items():
        actual = snapshot_kpis.get(metric, float('nan'))
        target_str = f"{op} {threshold}"
        
        if actual != actual:
            status = "MISSING"
        else:
            passed = (actual >= threshold) if op == ">=" else (actual <= threshold)
            status = f"{sym('ok')} PASS" if passed else f"{sym('fail')} FAIL"
        
        md_lines.append(f"| {metric} | {target_str} | {actual:.3f} | {status} |")
    
    md_lines.extend([
        f"",
        f"**Verdict:** {f'{sym(\"ok\")} READINESS: OK' if all_pass else f'{sym(\"fail\")} READINESS: HOLD'}",
        f"",
    ])
    
    if not all_pass:
        md_lines.append(f"**Failures:**")
        for failure in failures:
            md_lines.append(f"- {failure}")
        md_lines.append(f"")
    
    md_lines.extend([
        f"---",
        f"",
        f"## Trend Statistics",
        f"",
        f"| Metric | Window | Min | Max | Median |",
        f"|--------|--------|-----|-----|--------|",
    ])
    
    for col in kpi_columns:
        for window in ["overall", "steady", "last8"]:
            stats = trend_stats[col][window]
            md_lines.append(
                f"| {col} | {window} | {stats['min']:.2f} | {stats['max']:.2f} | {stats['median']:.2f} |"
            )
    
    md_lines.extend([
        f"",
        f"---",
        f"",
        f"## Tuning & Delta Verification",
        f"",
    ])
    
    if tuning_summary["found"]:
        md_lines.append(f"**TUNING_REPORT.json:**")
        md_lines.append(f"- Deltas: {tuning_summary.get('applied_total', 0)}/{tuning_summary.get('proposed_total', 0)} applied")
        
        if tuning_summary.get("skip_reasons"):
            md_lines.append(f"- Guard skip reasons:")
            for reason, count in sorted(tuning_summary["skip_reasons"].items(), key=lambda x: -x[1])[:5]:
                md_lines.append(f"  - `{reason}`: {count}")
        md_lines.append(f"")
    
    if delta_verify_summary["found"]:
        md_lines.append(f"**DELTA_VERIFY_REPORT.md:**")
        if "full_pct" in delta_verify_summary:
            md_lines.append(
                f"- Full applications: {delta_verify_summary['full_applied']}/{delta_verify_summary['full_total']} "
                f"({delta_verify_summary['full_pct']}%)"
            )
        md_lines.append(f"")
    
    if warmup_summary["found"]:
        md_lines.append(f"**warmup_metrics.prom:**")
        if "exporter_error" in warmup_summary:
            md_lines.append(f"- Exporter errors: {warmup_summary['exporter_error']}")
        if warmup_summary.get("guard_triggers"):
            md_lines.append(f"- Guard triggers:")
            for gtype, count in sorted(warmup_summary["guard_triggers"].items()):
                md_lines.append(f"  - `{gtype}`: {count}")
        md_lines.append(f"")
    
    md_lines.extend([
        f"---",
        f"",
        f"## Recommendations",
        f"",
    ])
    
    for rec in recommendations:
        md_lines.append(rec)
    
    md_lines.extend([
        f"",
        f"---",
        f"",
        f"## Data Files",
        f"",
        f"- CSV table: `{out_csv_path.name}`",
        f"- JSON summary: `{out_json_path.name}`",
        f"",
        f"---",
        f"",
        f"*Generated by `tools.soak.audit_artifacts`*",
    ])
    
    with open(out_md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_lines))
    
    puts(f"{sym('ok')} Saved Markdown: {out_md_path}")
    
    # Save JSON summary
    json_summary = {
        "timestamp": timestamp,
        "base_dir": str(base_dir),
        "iterations": len(iter_data),
        "max_iter": int(max_iter),
        "steady_start": STEADY_START_ITER,
        "last8_start": int(last_8_start),
        "files_present": files_present,
        "snapshot_kpis": {k: (v if v == v else None) for k, v in snapshot_kpis.items()},
        "readiness": {
            "pass": all_pass,
            "failures": failures,
        },
        "trend_stats": {
            col: {
                window: {k: (v if v == v else None) for k, v in stats.items()}
                for window, stats in windows.items()
            }
            for col, windows in trend_stats.items()
        },
        "tuning": tuning_summary,
        "delta_verify": delta_verify_summary,
        "warmup": warmup_summary,
        "recommendations": recommendations,
    }
    
    with open(out_json_path, 'w', encoding='utf-8') as f:
        json.dump(json_summary, f, indent=2)
    
    puts(f"{sym('ok')} Saved JSON: {out_json_path}")
    print()
    
    # ----- 11. Print report preview -----
    print("[11/11] Report Preview:")
    print()
    print("=" * 80)
    for line in md_lines[:30]:
        print(line)
    print("...")
    print("=" * 80)
    print()
    
    print(f"📄 Full report: {out_md_path}")
    print(f"📊 JSON summary: {out_json_path}")
    print(f"📈 CSV table: {out_csv_path}")
    print()
    
    # Final verdict
    verdict = "READINESS: OK" if all_pass else f"READINESS: HOLD ({len(failures)} KPI(s) failed)"
    print("=" * 80)
    print(f"🎯 FINAL VERDICT: {verdict}")
    print("=" * 80)
    print()
    
    # ----- 12. Generate plots (optional) -----
    if generate_plots:
        print("[12/12] Generating plots...")
        
        if not HAS_MATPLOTLIB:
            puts(f"{sym('warn')} WARNING: matplotlib not available; skipping plots")
        else:
            plots_dir = out_dir / "plots"
            plots_dir.mkdir(parents=True, exist_ok=True)
            
            kpi_columns = ["net_bps", "risk_ratio", "latency_p95_ms", "maker_taker_ratio"]
            
            if HAS_PANDAS:
                for col in kpi_columns:
                    try:
                        plt.figure(figsize=(10, 6))
                        plt.plot(df["iter"], df[col], marker='o', linestyle='-', linewidth=2)
                        plt.xlabel("Iteration")
                        plt.ylabel(col)
                        plt.title(f"{col} vs Iteration")
                        plt.grid(True, alpha=0.3)
                        
                        # Add threshold line if applicable
                        if col in ["maker_taker_ratio", "net_bps", "p95_latency_ms", "risk_ratio"]:
                            for metric, (op, threshold) in READINESS_THRESHOLDS.items():
                                if metric == col or (metric == "p95_latency_ms" and col == "latency_p95_ms"):
                                    plt.axhline(y=threshold, color='r', linestyle='--', 
                                               label=f"Threshold {op} {threshold}")
                                    plt.legend()
                                    break
                        
                        plot_path = plots_dir / f"{col}.png"
                        plt.savefig(plot_path, dpi=100, bbox_inches='tight')
                        plt.close()
                        puts(f"  {sym('ok')} Saved: {plot_path.name}")
                    except Exception as e:
                        puts(f"  {sym('warn')} Failed to generate {col}.png: {e}")
            else:
                puts(f"  {sym('warn')} pandas not available; cannot generate plots")
            
            print()
    
    return json_summary


# ==============================================================================
# CLI
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Audit soak test artifacts and generate comprehensive report"
    )
    parser.add_argument(
        "--base",
        default="artifacts/soak/latest",
        help="Base directory for soak artifacts (default: artifacts/soak/latest)"
    )
    parser.add_argument(
        "--fail-on-hold",
        action="store_true",
        help="Exit with code 1 if readiness is HOLD (default: False)"
    )
    parser.add_argument(
        "--plots",
        action="store_true",
        help="Generate PNG plots if matplotlib available (default: False)"
    )
    
    args = parser.parse_args()
    
    try:
        result = audit_artifacts(args.base, generate_plots=args.plots)
        readiness_pass = result.get("readiness", {}).get("pass", False)
        
        # Determine exit code
        exit_code = 0
        if args.fail_on_hold and not readiness_pass:
            exit_code = 1
        
        verdict = "OK" if readiness_pass else "HOLD"
        print(f"[EXIT] fail-on-hold: {args.fail_on_hold}, verdict: {verdict}, exit_code={exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
        sys.exit(1)
    except Exception as e:
        puts(f"\n{sym('fail')} FATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


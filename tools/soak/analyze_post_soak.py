#!/usr/bin/env python3
"""
Post-Soak Deep Report Generator for mm-bot

Analyzes soak test results from artifacts/soak/latest/ directory and generates:
- POST_SOAK_AUDIT.md: Full analysis with KPI trends, guards, anomalies
- RECOMMENDATIONS.md: Proposed parameter deltas based on KPI violations
- FAILURES.md: Detailed failure analysis (only if verdict is FAIL)

Usage:
    python -m tools.soak.analyze_post_soak [--path PATH]

Exit codes:
    0 = PASS or WARN
    1 = FAIL or critical error
"""

import glob
import json
import sys
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev
from typing import Dict, List, Any, Optional, Tuple


# ==============================================================================
# KPI THRESHOLDS (HARD)
# ==============================================================================

KPI_THRESHOLDS = {
    "risk_ratio": 0.42,         # max
    "maker_taker_ratio": 0.85,  # min
    "net_bps": 2.7,             # min
    "p95_latency_ms": 350,      # max
}

# PASS criteria: last 8 iterations, ≥6 pass all KPI + freeze_triggered at least once
PASS_WINDOW = 8
PASS_MIN_COUNT = 6


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON file with error handling."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to load {path}: {e}", file=sys.stderr)
        return None


def load_iter_summaries(base_path: Path) -> List[Dict[str, Any]]:
    """Load all ITER_SUMMARY_*.json files, sorted by iteration number."""
    pattern = str(base_path / "ITER_SUMMARY_*.json")
    files = glob.glob(pattern)
    
    summaries = []
    for fpath in files:
        # Extract iteration number from filename
        match = re.search(r'ITER_SUMMARY_(\d+)\.json', fpath)
        if not match:
            continue
        
        data = load_json_safe(Path(fpath))
        if data:
            summaries.append(data)
    
    # Sort by iteration number
    summaries.sort(key=lambda x: x.get("iteration", 0))
    return summaries


def check_kpi(summary: Dict[str, Any]) -> Dict[str, bool]:
    """Check if iteration passes all KPI thresholds."""
    s = summary.get("summary", summary)
    
    checks = {
        "risk_ratio": s.get("risk_ratio", 1.0) <= KPI_THRESHOLDS["risk_ratio"],
        "maker_taker_ratio": s.get("maker_taker_ratio", 0.0) >= KPI_THRESHOLDS["maker_taker_ratio"],
        "net_bps": s.get("net_bps", 0.0) >= KPI_THRESHOLDS["net_bps"],
        "p95_latency_ms": s.get("p95_latency_ms", 9999) <= KPI_THRESHOLDS["p95_latency_ms"],
    }
    
    checks["all_pass"] = all(checks.values())
    return checks


def compute_last8_stats(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregates for last 8 iterations."""
    last8 = summaries[-PASS_WINDOW:] if len(summaries) >= PASS_WINDOW else summaries
    
    def extract_values(key: str) -> List[float]:
        values = []
        for item in last8:
            s = item.get("summary", item)
            val = s.get(key)
            if val is not None:
                values.append(float(val))
        return values
    
    stats = {}
    for key in ["risk_ratio", "maker_taker_ratio", "net_bps", "p95_latency_ms"]:
        values = extract_values(key)
        if values:
            stats[key] = {
                "mean": mean(values),
                "median": median(values),
                "min": min(values),
                "max": max(values),
                "stdev": stdev(values) if len(values) > 1 else 0.0,
            }
        else:
            stats[key] = {"mean": 0, "median": 0, "min": 0, "max": 0, "stdev": 0}
    
    return stats


def scan_guards(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Count guard activations and freeze events."""
    guards = {
        "oscillation_detected": 0,
        "velocity_violation": 0,
        "cooldown_active": 0,
        "freeze_triggered": 0,
        "freeze_events": [],
    }
    
    for item in summaries:
        tuning = item.get("tuning", {})
        
        if tuning.get("oscillation_detected"):
            guards["oscillation_detected"] += 1
        if tuning.get("velocity_violation"):
            guards["velocity_violation"] += 1
        if tuning.get("cooldown_active"):
            guards["cooldown_active"] += 1
        if tuning.get("freeze_triggered"):
            guards["freeze_triggered"] += 1
            guards["freeze_events"].append({
                "iteration": item.get("iteration"),
                "reason": tuning.get("freeze_reason", "unknown"),
            })
    
    return guards


def detect_signatures(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze runtime signatures and detect A→B→A loops."""
    signatures = []
    for item in summaries:
        tuning = item.get("tuning", {})
        sig = tuning.get("signature") or tuning.get("state_hash") or "na"
        signatures.append(sig)
    
    unique = list(set(signatures))
    
    # Detect A→B→A oscillations (3-window)
    loops = []
    for i in range(len(signatures) - 2):
        if signatures[i] == signatures[i+2] and signatures[i] != signatures[i+1]:
            loops.append({
                "iterations": [i+1, i+2, i+3],  # 1-based
                "pattern": f"{signatures[i][:8]}→{signatures[i+1][:8]}→{signatures[i+2][:8]}",
            })
    
    return {
        "unique_count": len(unique),
        "unique_sigs": [s[:12] for s in unique],
        "loops": loops,
    }


def detect_anomalies(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect anomalies: latency spikes, risk jumps, maker_taker drops."""
    anomalies = []
    
    for i, item in enumerate(summaries):
        s = item.get("summary", item)
        iteration = item.get("iteration", i+1)
        
        # Latency spike
        latency = s.get("p95_latency_ms", 0)
        if latency > KPI_THRESHOLDS["p95_latency_ms"] + 50:
            anomalies.append({
                "iteration": iteration,
                "type": "latency_spike",
                "value": latency,
                "threshold": KPI_THRESHOLDS["p95_latency_ms"] + 50,
            })
        
        # Risk jump (vs previous)
        if i > 0:
            prev_s = summaries[i-1].get("summary", summaries[i-1])
            prev_risk = prev_s.get("risk_ratio", 0)
            curr_risk = s.get("risk_ratio", 0)
            if curr_risk - prev_risk > 0.15:
                anomalies.append({
                    "iteration": iteration,
                    "type": "risk_jump",
                    "value": curr_risk,
                    "delta": curr_risk - prev_risk,
                })
        
        # Maker/Taker drop
        maker_taker = s.get("maker_taker_ratio", 1.0)
        if maker_taker < 0.75:
            anomalies.append({
                "iteration": iteration,
                "type": "maker_taker_drop",
                "value": maker_taker,
                "threshold": 0.75,
            })
    
    return anomalies


def make_deltas(stats: Dict[str, Any], guards: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Generate deterministic parameter delta recommendations."""
    deltas = {}
    
    # Risk too high → spread up, interval up
    if stats["risk_ratio"]["mean"] > KPI_THRESHOLDS["risk_ratio"]:
        deltas["base_spread_bps"] = {
            "current": "unknown",
            "delta": +0.03,
            "rationale": f"risk_ratio={stats['risk_ratio']['mean']:.3f} > {KPI_THRESHOLDS['risk_ratio']}"
        }
        deltas["min_interval_ms"] = {
            "current": "unknown",
            "delta": +35,
            "rationale": "Reduce order frequency to lower risk"
        }
    
    # Maker/Taker too low → spread up, replace rate down
    if stats["maker_taker_ratio"]["mean"] < KPI_THRESHOLDS["maker_taker_ratio"]:
        deltas["base_spread_bps"] = {
            "current": "unknown",
            "delta": +0.015,
            "rationale": f"maker_taker_ratio={stats['maker_taker_ratio']['mean']:.3f} < {KPI_THRESHOLDS['maker_taker_ratio']}"
        }
        deltas["replace_rate_per_min"] = {
            "current": "unknown",
            "delta": "*0.85",
            "rationale": "Reduce replace rate to stay on book longer"
        }
    
    # Latency too high → reduce concurrency, increase tail age
    if stats["p95_latency_ms"]["mean"] > KPI_THRESHOLDS["p95_latency_ms"]:
        deltas["concurrency_limit"] = {
            "current": "unknown",
            "delta": "*0.85",
            "rationale": f"p95_latency={stats['p95_latency_ms']['mean']:.1f}ms > {KPI_THRESHOLDS['p95_latency_ms']}"
        }
        deltas["tail_age_ms"] = {
            "current": "unknown",
            "delta": +75,
            "rationale": "Allow more age before replacement to reduce pressure"
        }
    
    # Oscillation detected → cooldown up, velocity down
    if guards["oscillation_detected"] > 1:
        deltas["cooldown_iters"] = {
            "current": "unknown",
            "delta": +1,
            "rationale": f"oscillation_detected={guards['oscillation_detected']} times"
        }
        deltas["max_delta_per_hour"] = {
            "current": "unknown",
            "delta": "*0.8",
            "rationale": "Slow down parameter changes to prevent oscillation"
        }
    
    # Velocity violation → velocity limit down
    if guards["velocity_violation"] > 0:
        deltas["max_delta_per_hour"] = {
            "current": "unknown",
            "delta": "*0.9",
            "rationale": f"velocity_violation={guards['velocity_violation']} times"
        }
    
    # Net BPS too low BUT risk is good → can tighten spreads
    if (stats["net_bps"]["mean"] < KPI_THRESHOLDS["net_bps"] and 
        stats["risk_ratio"]["mean"] <= 0.40):
        deltas["base_spread_bps"] = {
            "current": "unknown",
            "delta": -0.01,
            "rationale": f"net_bps={stats['net_bps']['mean']:.2f} low but risk={stats['risk_ratio']['mean']:.3f} OK"
        }
        deltas["min_interval_ms"] = {
            "current": "unknown",
            "delta": -20,
            "rationale": "Increase order frequency to capture more edge"
        }
    
    return deltas


def render_ascii_sparkline(values: List[float], width: int = 40) -> str:
    """Render ASCII sparkline using block characters."""
    if not values or len(values) == 0:
        return "N/A"
    
    min_val = min(values)
    max_val = max(values)
    
    if max_val == min_val:
        return "─" * width
    
    # Normalize to 0-7 (8 levels for block chars)
    blocks = "▁▂▃▄▅▆▇█"
    normalized = [(v - min_val) / (max_val - min_val) * 7 for v in values]
    
    # Sample to fit width
    step = max(1, len(values) // width)
    sampled = [normalized[i] for i in range(0, len(values), step)][:width]
    
    return "".join(blocks[int(v)] for v in sampled)


def read_edge_kpi(base_path: Path) -> Optional[Dict[str, Any]]:
    """Read EDGE_REPORT.json or KPI_GATE.json (priority order)."""
    candidates = [
        base_path.parent / "artifacts" / "EDGE_REPORT.json",
        base_path.parent / "artifacts" / "KPI_GATE.json",
        base_path.parent.parent / "reports" / "EDGE_REPORT.json",
        base_path / "EDGE_REPORT.json",
        base_path / "KPI_GATE.json",
    ]
    
    for path in candidates:
        if path.exists():
            return load_json_safe(path)
    
    return None


# ==============================================================================
# REPORT GENERATORS
# ==============================================================================

def generate_audit_report(
    summaries: List[Dict[str, Any]],
    stats: Dict[str, Any],
    guards: Dict[str, Any],
    signatures: Dict[str, Any],
    anomalies: List[Dict[str, Any]],
    edge_kpi: Optional[Dict[str, Any]],
    verdict: str,
    freeze_decision: str,
    base_path: Path,
) -> str:
    """Generate POST_SOAK_AUDIT.md content."""
    
    lines = []
    lines.append("# POST-SOAK AUDIT REPORT")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}Z")
    lines.append(f"**Source:** `{base_path}`")
    lines.append("")
    
    # Overview
    lines.append("## 1. Overview")
    lines.append("")
    lines.append(f"- **Total iterations:** {len(summaries)}")
    lines.append(f"- **Analysis window:** Last {min(PASS_WINDOW, len(summaries))} iterations")
    
    if summaries:
        first_ts = summaries[0].get("summary", {}).get("runtime_utc", "N/A")
        last_ts = summaries[-1].get("summary", {}).get("runtime_utc", "N/A")
        lines.append(f"- **Time range:** {first_ts} → {last_ts}")
    
    if edge_kpi:
        lines.append(f"- **KPI_GATE verdict:** {edge_kpi.get('verdict', 'N/A')}")
    
    lines.append("")
    
    # Iteration Matrix
    lines.append("## 2. Iteration Matrix")
    lines.append("")
    lines.append("```csv")
    lines.append("iteration,timestamp,risk_ratio,maker_taker,net_bps,p95_ms,applied,deltas_count,cooldown,velocity,oscillation,freeze,signature")
    
    for item in summaries:
        s = item.get("summary", item)
        t = item.get("tuning", {})
        
        idx = item.get("iteration", 0)
        ts = s.get("runtime_utc", "N/A")[:19]  # Truncate microseconds
        risk = s.get("risk_ratio", 0)
        maker = s.get("maker_taker_ratio", 0)
        net = s.get("net_bps", 0)
        p95 = s.get("p95_latency_ms", 0)
        applied = t.get("applied", False)
        deltas_count = len(t.get("proposed_deltas", {}))
        cooldown = t.get("cooldown_active", False)
        velocity = t.get("velocity_violation", False)
        oscillation = t.get("oscillation_detected", False)
        freeze = t.get("freeze_triggered", False)
        sig = (t.get("signature") or t.get("state_hash") or "na")[:8]
        
        # Check KPI pass
        kpi_check = check_kpi(item)
        status = "PASS" if kpi_check["all_pass"] else "FAIL"
        
        lines.append(
            f"{idx},{ts},{risk:.3f},{maker:.3f},{net:.2f},{p95:.0f},"
            f"{applied},{deltas_count},{cooldown},{velocity},{oscillation},{freeze},{sig} # {status}"
        )
    
    lines.append("```")
    lines.append("")
    
    # KPI Trends
    lines.append("## 3. KPI Trends (Last 8 Iterations)")
    lines.append("")
    lines.append("```")
    lines.append(f"{'Metric':<20} {'Mean':<10} {'Median':<10} {'Min':<10} {'Max':<10} {'StDev':<10} {'Threshold':<12} {'Pass?'}")
    lines.append("-" * 102)
    
    for key, label, threshold, comp in [
        ("risk_ratio", "Risk Ratio", KPI_THRESHOLDS["risk_ratio"], "<="),
        ("maker_taker_ratio", "Maker/Taker", KPI_THRESHOLDS["maker_taker_ratio"], ">="),
        ("net_bps", "Net BPS", KPI_THRESHOLDS["net_bps"], ">="),
        ("p95_latency_ms", "P95 Latency (ms)", KPI_THRESHOLDS["p95_latency_ms"], "<="),
    ]:
        st = stats[key]
        if comp == "<=":
            pass_check = st["mean"] <= threshold
        else:
            pass_check = st["mean"] >= threshold
        
        lines.append(
            f"{label:<20} {st['mean']:<10.3f} {st['median']:<10.3f} "
            f"{st['min']:<10.3f} {st['max']:<10.3f} {st['stdev']:<10.3f} "
            f"{comp} {threshold:<8} {'PASS' if pass_check else 'FAIL'}"
        )
    
    lines.append("```")
    lines.append("")
    
    # ASCII Sparklines
    lines.append("### Visual Trends")
    lines.append("")
    
    risk_values = [s.get("summary", s).get("risk_ratio", 0) for s in summaries]
    net_values = [s.get("summary", s).get("net_bps", 0) for s in summaries]
    
    lines.append(f"**Risk Ratio:**  `{render_ascii_sparkline(risk_values)}`")
    lines.append(f"**Net BPS:**     `{render_ascii_sparkline(net_values)}`")
    lines.append("")
    
    # Guards & Stability
    lines.append("## 4. Guards & Stability")
    lines.append("")
    lines.append(f"- **Oscillation detected:** {guards['oscillation_detected']} times")
    lines.append(f"- **Velocity violation:** {guards['velocity_violation']} times")
    lines.append(f"- **Cooldown active:** {guards['cooldown_active']} times")
    lines.append(f"- **Freeze triggered:** {guards['freeze_triggered']} times")
    
    if guards["freeze_events"]:
        lines.append("")
        lines.append("**Freeze Events:**")
        for event in guards["freeze_events"]:
            lines.append(f"  - Iteration {event['iteration']}: {event['reason']}")
    
    lines.append("")
    
    # Runtime Signatures
    lines.append("## 5. Runtime Signatures")
    lines.append("")
    lines.append(f"- **Unique signatures:** {signatures['unique_count']}")
    lines.append(f"- **Signatures:** {', '.join(signatures['unique_sigs'])}")
    
    if signatures["loops"]:
        lines.append("")
        lines.append("**A→B→A Oscillation Loops Detected:**")
        for loop in signatures["loops"]:
            lines.append(f"  - Iterations {loop['iterations']}: {loop['pattern']}")
    else:
        lines.append("- **Oscillation loops:** None detected [OK]")
    
    lines.append("")
    
    # Edge Drivers
    lines.append("## 6. Edge Decomposition")
    lines.append("")
    
    if edge_kpi and "edge_drivers" in edge_kpi:
        drivers = edge_kpi["edge_drivers"]
        lines.append("```")
        lines.append(f"{'Driver':<25} {'Value (bps)':<15} {'Impact'}")
        lines.append("-" * 50)
        for driver, value in sorted(drivers.items(), key=lambda x: abs(x[1]), reverse=True):
            impact = "▼ negative" if value < 0 else "▲ positive"
            lines.append(f"{driver:<25} {value:<15.2f} {impact}")
        lines.append("```")
        
        # Top 2 drivers
        sorted_drivers = sorted(drivers.items(), key=lambda x: abs(x[1]), reverse=True)[:2]
        lines.append("")
        lines.append("**Top Impact Drivers:**")
        for driver, value in sorted_drivers:
            lines.append(f"  - `{driver}`: {value:.2f} bps")
    else:
        lines.append("*No edge decomposition data available*")
    
    lines.append("")
    
    # Anomalies
    lines.append("## 7. Anomalies")
    lines.append("")
    
    if anomalies:
        for anom in anomalies:
            lines.append(f"- **Iteration {anom['iteration']}** ({anom['type']}): {anom}")
    else:
        lines.append("*No anomalies detected* [OK]")
    
    lines.append("")
    
    # Verdict & Actions
    lines.append("## 8. Verdict & Actions")
    lines.append("")
    lines.append(f"### Run Verdict: **{verdict}**")
    lines.append("")
    lines.append(f"### Freeze Decision: **{freeze_decision}**")
    lines.append("")
    
    if verdict == "PASS":
        lines.append("[OK] **Production Gate:** READY for 24h soak")
    elif verdict == "WARN":
        lines.append("[WARN] **Production Gate:** Review recommended before 24h soak")
    else:
        lines.append("[FAIL] **Production Gate:** HOLD — fixes required")
        lines.append("")
        lines.append("**Required Actions:**")
        lines.append("  - Review FAILURES.md for specific violations")
        lines.append("  - Apply recommended parameter deltas")
        lines.append("  - Re-run mini-soak validation")
    
    lines.append("")
    lines.append("---")
    lines.append("*Generated by tools/soak/analyze_post_soak.py*")
    
    return "\n".join(lines)


def generate_recommendations(
    stats: Dict[str, Any],
    guards: Dict[str, Any],
    deltas: Dict[str, Dict[str, Any]],
    freeze_decision: str,
) -> str:
    """Generate RECOMMENDATIONS.md content."""
    
    lines = []
    lines.append("# PARAMETER RECOMMENDATIONS")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}Z")
    lines.append("")
    
    # KPI Summary
    lines.append("## KPI Summary (Last 8 Iterations)")
    lines.append("")
    lines.append("```")
    for key, label in [
        ("risk_ratio", "Risk Ratio"),
        ("maker_taker_ratio", "Maker/Taker"),
        ("net_bps", "Net BPS"),
        ("p95_latency_ms", "P95 Latency"),
    ]:
        st = stats[key]
        lines.append(f"{label:<20} mean={st['mean']:.3f}  median={st['median']:.3f}")
    lines.append("```")
    lines.append("")
    
    # Proposed Deltas
    lines.append("## Proposed Parameter Deltas")
    lines.append("")
    
    if deltas:
        lines.append("```")
        lines.append(f"{'Parameter':<25} {'Current':<12} {'Proposed Delta':<20} {'Rationale'}")
        lines.append("-" * 100)
        
        for param, details in sorted(deltas.items()):
            current = details.get("current", "unknown")
            delta = details.get("delta", "N/A")
            rationale = details.get("rationale", "")[:60]  # Truncate for table
            
            lines.append(f"{param:<25} {current:<12} {delta:<20} {rationale}")
        
        lines.append("```")
    else:
        lines.append("*No parameter changes recommended* [OK]")
    
    lines.append("")
    
    # Freeze Decision
    lines.append("## Freeze Decision")
    lines.append("")
    lines.append(f"**{freeze_decision}**")
    
    if "READY" in freeze_decision:
        lines.append("")
        lines.append("[OK] Configuration is stable and ready for production freeze.")
    else:
        lines.append("")
        lines.append("[HOLD] Configuration requires further tuning before freeze.")
    
    lines.append("")
    lines.append("---")
    lines.append("*Generated by tools/soak/analyze_post_soak.py*")
    
    return "\n".join(lines)


def generate_failures(
    summaries: List[Dict[str, Any]],
    anomalies: List[Dict[str, Any]],
) -> str:
    """Generate FAILURES.md content (only for FAIL verdict)."""
    
    lines = []
    lines.append("# SOAK TEST FAILURES")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}Z")
    lines.append("")
    
    # KPI Violations
    lines.append("## KPI Violations")
    lines.append("")
    
    violations = []
    for item in summaries:
        kpi_check = check_kpi(item)
        if not kpi_check["all_pass"]:
            violations.append({
                "iteration": item.get("iteration", 0),
                "checks": kpi_check,
                "summary": item.get("summary", item),
            })
    
    if violations:
        for v in violations:
            lines.append(f"### Iteration {v['iteration']}")
            lines.append("")
            
            for key in ["risk_ratio", "maker_taker_ratio", "net_bps", "p95_latency_ms"]:
                passed = v["checks"][key]
                value = v["summary"].get(key, "N/A")
                threshold = KPI_THRESHOLDS[key]
                
                if not passed:
                    lines.append(f"- [FAIL] **{key}**: {value} (threshold: {threshold})")
            
            lines.append("")
            lines.append(f"**Reference:** `ITER_SUMMARY_{v['iteration']}.json`")
            lines.append("")
    else:
        lines.append("*No KPI violations detected*")
    
    lines.append("")
    
    # Anomalies
    lines.append("## Anomalies")
    lines.append("")
    
    if anomalies:
        for anom in anomalies:
            lines.append(f"- **Iteration {anom['iteration']}**: {anom['type']} — {anom}")
    else:
        lines.append("*No anomalies detected*")
    
    lines.append("")
    lines.append("---")
    lines.append("*Generated by tools/soak/analyze_post_soak.py*")
    
    return "\n".join(lines)


# ==============================================================================
# MAIN ANALYSIS FUNCTION
# ==============================================================================

def analyze_soak(base_path: Path) -> Tuple[str, int]:
    """
    Main analysis function.
    
    Returns:
        (verdict_string, exit_code)
    """
    
    print(f"[analyze_post_soak] Analyzing soak results from: {base_path}")
    
    # Load iteration summaries
    summaries = load_iter_summaries(base_path)
    
    if not summaries:
        print("[ERROR] No ITER_SUMMARY_*.json files found!", file=sys.stderr)
        return "FAIL (no_data)", 1
    
    print(f"[analyze_post_soak] Loaded {len(summaries)} iteration summaries")
    
    # Compute stats for last 8 iterations
    stats = compute_last8_stats(summaries)
    
    # Scan guards and freeze events
    guards = scan_guards(summaries)
    
    # Analyze runtime signatures
    signatures = detect_signatures(summaries)
    
    # Detect anomalies
    anomalies = detect_anomalies(summaries)
    
    # Read edge/KPI data
    edge_kpi = read_edge_kpi(base_path)
    
    # Generate parameter delta recommendations
    deltas = make_deltas(stats, guards)
    
    # Determine verdict
    last8 = summaries[-PASS_WINDOW:] if len(summaries) >= PASS_WINDOW else summaries
    pass_count = sum(1 for item in last8 if check_kpi(item)["all_pass"])
    freeze_occurred = guards["freeze_triggered"] > 0
    
    if pass_count >= PASS_MIN_COUNT and freeze_occurred:
        verdict = "PASS"
        exit_code = 0
    elif pass_count >= PASS_MIN_COUNT - 1:  # One less than threshold
        verdict = "WARN"
        exit_code = 0
    else:
        verdict = "FAIL"
        exit_code = 1
    
    # Freeze decision
    if verdict == "PASS" and freeze_occurred:
        freeze_decision = "READY_TO_FREEZE [OK]"
    else:
        freeze_decision = "HOLD [HOLD]"
    
    print(f"[analyze_post_soak] Verdict: {verdict} (pass_count={pass_count}/{len(last8)}, freeze={freeze_occurred})")
    
    # Generate reports
    print("[analyze_post_soak] Generating reports...")
    
    audit_md = generate_audit_report(
        summaries, stats, guards, signatures, anomalies, 
        edge_kpi, verdict, freeze_decision, base_path
    )
    
    recommendations_md = generate_recommendations(stats, guards, deltas, freeze_decision)
    
    failures_md = None
    if verdict == "FAIL":
        failures_md = generate_failures(summaries, anomalies)
    
    # Write reports
    (base_path / "POST_SOAK_AUDIT.md").write_text(audit_md, encoding="utf-8")
    print(f"[analyze_post_soak] [OK] Written: {base_path / 'POST_SOAK_AUDIT.md'}")
    
    (base_path / "RECOMMENDATIONS.md").write_text(recommendations_md, encoding="utf-8")
    print(f"[analyze_post_soak] [OK] Written: {base_path / 'RECOMMENDATIONS.md'}")
    
    if failures_md:
        (base_path / "FAILURES.md").write_text(failures_md, encoding="utf-8")
        print(f"[analyze_post_soak] [OK] Written: {base_path / 'FAILURES.md'}")
    
    # Print verdict
    reason = f"pass_count={pass_count}/{len(last8)}, freeze={freeze_occurred}"
    verdict_str = f"POST_SOAK: {verdict} ({reason})"
    
    return verdict_str, exit_code


# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================

def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Post-Soak Deep Report Generator")
    parser.add_argument(
        "--path",
        type=str,
        default="artifacts/soak/latest 1/soak/latest",
        help="Path to soak/latest directory (default: artifacts/soak/latest 1/soak/latest)"
    )
    
    args = parser.parse_args()
    
    base_path = Path(args.path).resolve()
    
    if not base_path.exists():
        print(f"[ERROR] Path does not exist: {base_path}", file=sys.stderr)
        sys.exit(1)
    
    verdict_str, exit_code = analyze_soak(base_path)
    
    print("")
    print("=" * 80)
    print(verdict_str)
    print("=" * 80)
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()


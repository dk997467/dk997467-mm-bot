#!/usr/bin/env python3
"""
Extract Post-Soak Snapshot (compact JSON summary).

Reads POST_SOAK_SUMMARY.json or computes from ITER_SUMMARY_*.json files.
Outputs deterministic JSON with verdict, KPI stats, guard counts, and metadata.

Usage:
    python -m tools.soak.extract_post_soak_snapshot [--path PATH] [--pretty]

Output:
    - stdout: JSON (single line or pretty-printed)
    - file: POST_SOAK_SNAPSHOT.json in same directory

Schema version: 1.1
"""

import glob
import json
import re
import sys
from pathlib import Path
from statistics import mean, median
from typing import Dict, List, Any, Optional, Tuple
from urllib import request
from urllib.error import URLError


# KPI thresholds for pass criteria
KPI_THRESHOLDS = {
    "risk_ratio": 0.42,
    "maker_taker_ratio": 0.85,
    "net_bps": 2.7,
    "p95_latency_ms": 350,
}


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON file with error handling."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _iter_files(base_path: Path) -> List[Path]:
    """Find and sort ITER_SUMMARY_*.json files by iteration number."""
    pattern = str(base_path / "ITER_SUMMARY_*.json")
    files = glob.glob(pattern)
    
    # Extract iteration numbers and sort
    def get_iter_num(fpath: str) -> int:
        match = re.search(r'ITER_SUMMARY_(\d+)\.json', fpath)
        return int(match.group(1)) if match else 0
    
    sorted_files = sorted(files, key=get_iter_num)
    return [Path(f) for f in sorted_files]


def _load_last8(base_path: Path) -> List[Dict[str, Any]]:
    """Load last 8 ITER_SUMMARY files."""
    files = _iter_files(base_path)
    last8_files = files[-8:] if len(files) >= 8 else files
    
    summaries = []
    for fpath in last8_files:
        data = _load_json_safe(fpath)
        if data:
            summaries.append(data)
    
    return summaries


def _stats(values: List[float]) -> Dict[str, float]:
    """Compute mean and median, rounded to 3 decimals."""
    if not values:
        return {"mean": 0.0, "median": 0.0}
    return {
        "mean": round(mean(values), 3),
        "median": round(median(values), 3),
    }


def _count_guards(summaries: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count guard activations from last 8 iterations."""
    guards = {
        "oscillation_count": 0,
        "velocity_count": 0,
        "cooldown_count": 0,
        "freeze_events": 0,
    }
    
    for item in summaries:
        tuning = item.get("tuning", {})
        
        if tuning.get("oscillation_detected"):
            guards["oscillation_count"] += 1
        if tuning.get("velocity_violation"):
            guards["velocity_count"] += 1
        if tuning.get("cooldown_active"):
            guards["cooldown_count"] += 1
        if tuning.get("freeze_triggered"):
            guards["freeze_events"] += 1
    
    return guards


def _kpi_pass(summary: Dict[str, Any]) -> bool:
    """Check if iteration passes all KPI thresholds."""
    s = summary.get("summary", summary)
    
    return (
        s.get("risk_ratio", 1.0) <= KPI_THRESHOLDS["risk_ratio"]
        and s.get("maker_taker_ratio", 0.0) >= KPI_THRESHOLDS["maker_taker_ratio"]
        and s.get("net_bps", 0.0) >= KPI_THRESHOLDS["net_bps"]
        and s.get("p95_latency_ms", 9999) <= KPI_THRESHOLDS["p95_latency_ms"]
    )


def _extract_time_range(summaries: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Extract time range from summaries (earliest → latest timestamp)."""
    timestamps = []
    for item in summaries:
        s = item.get("summary", item)
        ts = s.get("runtime_utc")
        if ts:
            timestamps.append(ts)
    
    if not timestamps:
        return {"from": None, "to": None}
    
    return {
        "from": min(timestamps),
        "to": max(timestamps),
    }


def _check_kpi_gate_parity(base_path: Path, snapshot_verdict: str) -> Optional[bool]:
    """Check if snapshot verdict matches KPI_GATE.json verdict."""
    kpi_gate_path = base_path / "KPI_GATE.json"
    
    if not kpi_gate_path.exists():
        return None  # No KPI_GATE.json file
    
    kpi_gate = _load_json_safe(kpi_gate_path)
    if not kpi_gate:
        return None
    
    gate_verdict = kpi_gate.get("verdict")
    if not gate_verdict:
        return None
    
    return snapshot_verdict == gate_verdict


def _count_anomalies(summaries: List[Dict[str, Any]]) -> int:
    """
    Count anomalies in last 8 iterations.
    
    Anomalies:
    - latency_spike: p95_latency_ms > 350 + 50
    - risk_jump: Δrisk > +0.15 vs previous iteration
    - maker_taker_drop: maker_taker_ratio < 0.75
    """
    anomaly_count = 0
    
    for i, item in enumerate(summaries):
        s = item.get("summary", item)
        
        # Latency spike
        latency = s.get("p95_latency_ms", 0)
        if latency > 400:  # 350 + 50
            anomaly_count += 1
        
        # Risk jump (vs previous)
        if i > 0:
            prev_s = summaries[i-1].get("summary", summaries[i-1])
            prev_risk = prev_s.get("risk_ratio", 0)
            curr_risk = s.get("risk_ratio", 0)
            if curr_risk - prev_risk > 0.15:
                anomaly_count += 1
        
        # Maker/Taker drop
        maker_taker = s.get("maker_taker_ratio", 1.0)
        if maker_taker < 0.75:
            anomaly_count += 1
    
    return anomaly_count


def _detect_signature_loops(summaries: List[Dict[str, Any]]) -> int:
    """
    Detect A→B→A signature oscillation loops (3-window).
    
    Returns count of such loops.
    """
    signatures = []
    for item in summaries:
        tuning = item.get("tuning", {})
        sig = tuning.get("signature") or tuning.get("state_hash") or "na"
        signatures.append(sig)
    
    if len(signatures) < 3:
        return 0
    
    loop_count = 0
    for i in range(len(signatures) - 2):
        # A→B→A pattern: signatures[i] == signatures[i+2] and signatures[i] != signatures[i+1]
        if signatures[i] == signatures[i+2] and signatures[i] != signatures[i+1]:
            loop_count += 1
    
    return loop_count


def _extract_from_summary(summary_path: Path) -> Dict[str, Any]:
    """Extract snapshot from POST_SOAK_SUMMARY.json (if exists)."""
    data = _load_json_safe(summary_path)
    if not data:
        return {}
    
    # Extract basic fields
    snapshot = {
        "verdict": data.get("verdict", "UNKNOWN"),
        "pass_count_last8": data.get("pass_count_last8", 0),
        "freeze_seen": data.get("freeze_seen", False),
    }
    
    # Extract KPI stats
    kpi_data = data.get("kpi", {})
    kpi_last8 = {}
    
    for key in ["risk_ratio", "maker_taker_ratio", "net_bps", "p95_latency_ms"]:
        kpi_stats = kpi_data.get(key, {})
        kpi_last8[key] = {
            "mean": round(kpi_stats.get("mean", 0.0), 3),
            "median": round(kpi_stats.get("median", 0.0), 3),
        }
    
    snapshot["kpi_last8"] = kpi_last8
    
    # Extract guards
    guards_data = data.get("guards", {})
    snapshot["guards_last8"] = {
        "oscillation_count": guards_data.get("oscillation_count", 0),
        "velocity_count": guards_data.get("velocity_count", 0),
        "cooldown_count": guards_data.get("cooldown_count", 0),
        "freeze_events": guards_data.get("freeze_events", 0),
    }
    
    return snapshot


def _extract_from_iters(base_path: Path) -> Dict[str, Any]:
    """Extract snapshot by computing from ITER_SUMMARY_*.json files."""
    summaries = _load_last8(base_path)
    
    if not summaries:
        return {}
    
    # Collect KPI values
    kpi_values = {
        "risk_ratio": [],
        "maker_taker_ratio": [],
        "net_bps": [],
        "p95_latency_ms": [],
    }
    
    for item in summaries:
        s = item.get("summary", item)
        for key in kpi_values.keys():
            val = s.get(key)
            if val is not None:
                kpi_values[key].append(float(val))
    
    # Compute stats
    kpi_last8 = {key: _stats(vals) for key, vals in kpi_values.items()}
    
    # Count guards
    guards_last8 = _count_guards(summaries)
    
    # Count pass iterations
    pass_count = sum(1 for item in summaries if _kpi_pass(item))
    
    # Check if freeze occurred
    freeze_seen = any(
        item.get("tuning", {}).get("freeze_triggered") for item in summaries
    )
    
    # Determine verdict (simple heuristic)
    if pass_count >= 6 and freeze_seen:
        verdict = "PASS"
    elif pass_count >= 5:
        verdict = "WARN"
    else:
        verdict = "FAIL"
    
    # Compute metadata fields
    freeze_ready = verdict in ("PASS", "WARN") and pass_count >= 6 and freeze_seen
    time_range = _extract_time_range(summaries)
    kpi_gate_parity = _check_kpi_gate_parity(base_path, verdict)
    anomalies_count = _count_anomalies(summaries)
    signature_loops = _detect_signature_loops(summaries)
    
    return {
        "schema_version": "1.1",
        "verdict": verdict,
        "pass_count_last8": pass_count,
        "freeze_seen": freeze_seen,
        "freeze_ready": freeze_ready,
        "kpi_last8": kpi_last8,
        "guards_last8": guards_last8,
        "time_range": time_range,
        "kpi_gate_parity": kpi_gate_parity,
        "anomalies_count": anomalies_count,
        "signature_loops": signature_loops,
    }


def _compare_baseline(current: Dict[str, Any], baseline_path: Path) -> str:
    """
    Compare current snapshot with baseline.
    
    Returns formatted diff string.
    """
    baseline = _load_json_safe(baseline_path)
    if not baseline:
        return "[WARN] Could not load baseline snapshot"
    
    lines = ["", "Baseline vs Current:"]
    
    kpi_keys = ["risk_ratio", "maker_taker_ratio", "net_bps", "p95_latency_ms"]
    
    for key in kpi_keys:
        curr_mean = current.get("kpi_last8", {}).get(key, {}).get("mean", 0)
        base_mean = baseline.get("kpi_last8", {}).get(key, {}).get("mean", 0)
        
        if base_mean == 0:
            continue
        
        delta = curr_mean - base_mean
        pct = (delta / base_mean) * 100 if base_mean != 0 else 0
        
        sign = "+" if delta >= 0 else ""
        lines.append(
            f"  {key}.mean: {base_mean:.3f} → {curr_mean:.3f} ({sign}{pct:.1f}%)"
        )
    
    # Verdict comparison
    curr_verdict = current.get("verdict", "UNKNOWN")
    base_verdict = baseline.get("verdict", "UNKNOWN")
    if curr_verdict != base_verdict:
        lines.append(f"  verdict: {base_verdict} → {curr_verdict}")
    
    return "\n".join(lines)


def _export_prometheus(snapshot: Dict[str, Any], output_path: Path):
    """Export snapshot metrics in Prometheus format."""
    lines = [
        "# HELP soak_kpi_risk_ratio_mean Risk ratio mean (last 8 iterations)",
        "# TYPE soak_kpi_risk_ratio_mean gauge",
        f"soak_kpi_risk_ratio_mean {snapshot.get('kpi_last8', {}).get('risk_ratio', {}).get('mean', 0)}",
        "",
        "# HELP soak_kpi_maker_taker_mean Maker/Taker ratio mean",
        "# TYPE soak_kpi_maker_taker_mean gauge",
        f"soak_kpi_maker_taker_mean {snapshot.get('kpi_last8', {}).get('maker_taker_ratio', {}).get('mean', 0)}",
        "",
        "# HELP soak_kpi_net_bps_mean Net BPS mean",
        "# TYPE soak_kpi_net_bps_mean gauge",
        f"soak_kpi_net_bps_mean {snapshot.get('kpi_last8', {}).get('net_bps', {}).get('mean', 0)}",
        "",
        "# HELP soak_kpi_latency_p95_mean P95 latency mean (ms)",
        "# TYPE soak_kpi_latency_p95_mean gauge",
        f"soak_kpi_latency_p95_mean {snapshot.get('kpi_last8', {}).get('p95_latency_ms', {}).get('mean', 0)}",
        "",
        "# HELP soak_guards_velocity_count Velocity violation count",
        "# TYPE soak_guards_velocity_count counter",
        f"soak_guards_velocity_count {snapshot.get('guards_last8', {}).get('velocity_count', 0)}",
        "",
        "# HELP soak_guards_cooldown_count Cooldown activation count",
        "# TYPE soak_guards_cooldown_count counter",
        f"soak_guards_cooldown_count {snapshot.get('guards_last8', {}).get('cooldown_count', 0)}",
        "",
        "# HELP soak_guards_oscillation_count Oscillation detection count",
        "# TYPE soak_guards_oscillation_count counter",
        f"soak_guards_oscillation_count {snapshot.get('guards_last8', {}).get('oscillation_count', 0)}",
        "",
        "# HELP soak_verdict_pass_count Passing iterations (last 8)",
        "# TYPE soak_verdict_pass_count gauge",
        f"soak_verdict_pass_count {snapshot.get('pass_count_last8', 0)}",
        "",
        "# HELP soak_freeze_ready Freeze readiness (1=ready, 0=not ready)",
        "# TYPE soak_freeze_ready gauge",
        f"soak_freeze_ready {1 if snapshot.get('freeze_ready') else 0}",
        "",
        "# HELP soak_anomalies_count Anomaly count (last 8)",
        "# TYPE soak_anomalies_count counter",
        f"soak_anomalies_count {snapshot.get('anomalies_count', 0)}",
        "",
    ]
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _send_notification(
    platform: str,
    webhook_url: str,
    snapshot: Dict[str, Any]
):
    """Send notification via webhook (Slack/Telegram)."""
    verdict = snapshot.get("verdict", "UNKNOWN")
    
    if verdict not in ("FAIL", "WARN"):
        return  # Only notify on failures/warnings
    
    # Extract KPI values
    kpi = snapshot.get("kpi_last8", {})
    risk = kpi.get("risk_ratio", {}).get("mean", 0)
    mt = kpi.get("maker_taker_ratio", {}).get("mean", 0)
    net = kpi.get("net_bps", {}).get("mean", 0)
    latency = kpi.get("p95_latency_ms", {}).get("mean", 0)
    
    guards = snapshot.get("guards_last8", {})
    guards_total = (
        guards.get("oscillation_count", 0)
        + guards.get("velocity_count", 0)
        + guards.get("cooldown_count", 0)
    )
    
    # Format message
    emoji = "[FAIL]" if verdict == "FAIL" else "[WARN]"
    message = (
        f"Soak {emoji} {verdict} | "
        f"risk={risk:.2f} | mt={mt:.2f} | net={net:.2f} | "
        f"latency={latency:.0f}ms | guards={guards_total}"
    )
    
    # Prepare payload
    if platform.lower() == "slack":
        payload = {"text": message}
    elif platform.lower() == "telegram":
        payload = {"text": message}
    else:
        print(f"[WARN] Unknown platform: {platform}", file=sys.stderr)
        return
    
    # Send webhook
    try:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        with request.urlopen(req, timeout=10) as response:
            if response.status in (200, 201, 204):
                print(f"[OK] Notification sent to {platform}", file=sys.stderr)
            else:
                print(
                    f"[WARN] Notification returned status {response.status}",
                    file=sys.stderr
                )
    except URLError as e:
        print(f"[ERROR] Failed to send notification: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Notification error: {e}", file=sys.stderr)


def extract_snapshot(base_path: Path) -> Tuple[Dict[str, Any], int]:
    """
    Extract post-soak snapshot.
    
    Returns:
        (snapshot_dict, exit_code)
    """
    
    # Try POST_SOAK_SUMMARY.json first
    summary_path = base_path / "POST_SOAK_SUMMARY.json"
    if summary_path.exists():
        snapshot = _extract_from_summary(summary_path)
        if snapshot:
            # Enrich with metadata fields if not present
            summaries = _load_last8(base_path)
            if summaries:
                snapshot.setdefault("schema_version", "1.1")
                
                # freeze_ready
                freeze_ready = (
                    snapshot.get("verdict") in ("PASS", "WARN")
                    and snapshot.get("pass_count_last8", 0) >= 6
                    and snapshot.get("freeze_seen", False)
                )
                snapshot.setdefault("freeze_ready", freeze_ready)
                
                # time_range
                snapshot.setdefault("time_range", _extract_time_range(summaries))
                
                # kpi_gate_parity
                snapshot.setdefault(
                    "kpi_gate_parity",
                    _check_kpi_gate_parity(base_path, snapshot.get("verdict", "UNKNOWN"))
                )
                
                # anomalies_count
                snapshot.setdefault("anomalies_count", _count_anomalies(summaries))
                
                # signature_loops
                snapshot.setdefault("signature_loops", _detect_signature_loops(summaries))
            
            return snapshot, 0
    
    # Fallback: compute from ITER_SUMMARY_*.json
    snapshot = _extract_from_iters(base_path)
    if not snapshot:
        print(
            "[ERROR] No data found: missing both POST_SOAK_SUMMARY.json and ITER_SUMMARY_*.json",
            file=sys.stderr
        )
        return {}, 1
    
    return snapshot, 0


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Extract Post-Soak Snapshot (compact JSON summary)"
    )
    parser.add_argument(
        "--path",
        type=str,
        default="artifacts/soak/latest 1/soak/latest",
        help="Path to soak/latest directory (default: artifacts/soak/latest 1/soak/latest)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON with indentation (default: single-line)",
    )
    parser.add_argument(
        "--compare",
        type=str,
        metavar="BASELINE_PATH",
        help="Compare with baseline snapshot (path to baseline POST_SOAK_SNAPSHOT.json)",
    )
    parser.add_argument(
        "--prometheus",
        action="store_true",
        help="Export metrics in Prometheus format (POST_SOAK_METRICS.prom)",
    )
    parser.add_argument(
        "--notify",
        type=str,
        choices=["slack", "telegram"],
        help="Send notification on FAIL/WARN (requires --webhook-url)",
    )
    parser.add_argument(
        "--webhook-url",
        type=str,
        help="Webhook URL for notifications",
    )
    
    args = parser.parse_args()
    
    base_path = Path(args.path).resolve()
    
    if not base_path.exists():
        print(f"[ERROR] Path does not exist: {base_path}", file=sys.stderr)
        sys.exit(1)
    
    # Extract snapshot
    snapshot, exit_code = extract_snapshot(base_path)
    
    if exit_code != 0:
        sys.exit(exit_code)
    
    # Write JSON (pretty or compact)
    if args.pretty:
        json_str = json.dumps(
            snapshot, sort_keys=True, indent=2, ensure_ascii=True
        )
    else:
        json_str = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    
    # Print to stdout
    print(json_str)
    
    # Write to file (always compact for file)
    output_path = base_path / "POST_SOAK_SNAPSHOT.json"
    json_compact = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(json_compact)
        f.write("\n")
    
    print(f"\n[OK] Snapshot written to: {output_path}", file=sys.stderr)
    
    # Baseline comparison
    if args.compare:
        baseline_path = Path(args.compare).resolve()
        if baseline_path.exists():
            diff = _compare_baseline(snapshot, baseline_path)
            print(diff, file=sys.stderr)
        else:
            print(f"[WARN] Baseline not found: {baseline_path}", file=sys.stderr)
    
    # Prometheus export
    if args.prometheus:
        prom_path = base_path / "POST_SOAK_METRICS.prom"
        _export_prometheus(snapshot, prom_path)
        print(f"[OK] Prometheus metrics written to: {prom_path}", file=sys.stderr)
    
    # Notifications
    if args.notify:
        if not args.webhook_url:
            print("[ERROR] --notify requires --webhook-url", file=sys.stderr)
            sys.exit(1)
        _send_notification(args.notify, args.webhook_url, snapshot)
    
    sys.exit(0)


if __name__ == "__main__":
    main()


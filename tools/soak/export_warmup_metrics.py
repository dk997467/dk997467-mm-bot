#!/usr/bin/env python3
"""
Export warm-up metrics for Prometheus/Grafana monitoring.

Usage:
    python -m tools.soak.export_warmup_metrics --path artifacts/soak/latest --output metrics.prom
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any


def load_iter_summaries(soak_dir: Path) -> List[Dict[str, Any]]:
    """Load all ITER_SUMMARY files from soak directory."""
    summaries = []
    
    for i in range(1, 100):  # Max 100 iterations
        iter_file = soak_dir / f"ITER_SUMMARY_{i}.json"
        if not iter_file.exists():
            break
        
        try:
            with open(iter_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                summaries.append(data)
        except Exception as e:
            print(f"[WARN] Failed to load {iter_file}: {e}", file=sys.stderr)
    
    return summaries


def load_tuning_report(soak_dir: Path) -> Dict[str, Any]:
    """Load TUNING_REPORT.json from soak directory."""
    report_file = soak_dir / "TUNING_REPORT.json"
    
    if not report_file.exists():
        return {}
    
    try:
        with open(report_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to load tuning report: {e}", file=sys.stderr)
        return {}


def export_warmup_metrics(summaries: List[Dict[str, Any]], tuning: Dict[str, Any]) -> str:
    """Export warm-up metrics in Prometheus format."""
    lines = []
    
    # Metadata
    lines.append("# HELP warmup_active Whether warm-up phase is currently active (1=yes, 0=no)")
    lines.append("# TYPE warmup_active gauge")
    
    lines.append("# HELP warmup_iter_idx Current iteration index within warm-up phase (0-4)")
    lines.append("# TYPE warmup_iter_idx gauge")
    
    lines.append("# HELP rampdown_active Whether ramp-down phase is currently active (1=yes, 0=no)")
    lines.append("# TYPE rampdown_active gauge")
    
    lines.append("# HELP soak_phase_name Current soak phase (0=warmup, 1=rampdown, 2=steady)")
    lines.append("# TYPE soak_phase_name gauge")
    
    lines.append("# HELP guard_triggers_total Total guard triggers by type")
    lines.append("# TYPE guard_triggers_total counter")
    
    lines.append("# HELP tuner_keys_changed_total Number of keys changed per iteration")
    lines.append("# TYPE tuner_keys_changed_total gauge")
    
    lines.append("# HELP kpi_gate_status KPI gate status per iteration (0=FAIL, 1=WARN, 2=OK)")
    lines.append("# TYPE kpi_gate_status gauge")
    
    # Per-iteration metrics
    for idx, summary_data in enumerate(summaries, start=1):
        summary = summary_data.get("summary", {})
        
        # Phase info
        phase = summary.get("phase", "STEADY")
        warmup_active = summary.get("warmup_active", 0)
        warmup_iter_idx = summary.get("warmup_iter_idx", 0)
        rampdown_active = summary.get("rampdown_active", 0)
        
        # Map phase to numeric
        phase_num = {"WARMUP": 0, "RAMPDOWN": 1, "STEADY": 2}.get(phase, 2)
        
        # Export phase metrics
        lines.append(f'warmup_active{{iteration="{idx}"}} {warmup_active}')
        lines.append(f'warmup_iter_idx{{iteration="{idx}"}} {warmup_iter_idx}')
        lines.append(f'rampdown_active{{iteration="{idx}"}} {rampdown_active}')
        lines.append(f'soak_phase_name{{iteration="{idx}",phase="{phase}"}} {phase_num}')
        
        # KPI metrics (enriched with phase)
        maker_taker = summary.get("maker_taker_ratio", 0.0)
        net_bps = summary.get("net_bps", 0.0)
        risk = summary.get("risk_ratio", 0.0)
        p95_latency = summary.get("p95_latency_ms", 0.0)
        
        lines.append(f'soak_maker_taker_ratio{{iteration="{idx}",phase="{phase}"}} {maker_taker}')
        lines.append(f'soak_net_bps{{iteration="{idx}",phase="{phase}"}} {net_bps}')
        lines.append(f'soak_risk_ratio{{iteration="{idx}",phase="{phase}"}} {risk}')
        lines.append(f'soak_p95_latency_ms{{iteration="{idx}",phase="{phase}"}} {p95_latency}')
    
    # Guard triggers from tuning report
    tuning_iters = tuning.get("iterations", [])
    guard_counts = {
        "velocity": 0,
        "latency_soft": 0,
        "latency_hard": 0,
        "oscillation": 0,
        "freeze": 0,
        "cooldown": 0
    }
    
    for iter_entry in tuning_iters:
        skip_reason = iter_entry.get("skip_reason", "")
        
        if "velocity" in skip_reason.lower():
            guard_counts["velocity"] += 1
        elif "latency" in skip_reason.lower():
            if "hard" in skip_reason.lower():
                guard_counts["latency_hard"] += 1
            else:
                guard_counts["latency_soft"] += 1
        elif "oscillation" in skip_reason.lower():
            guard_counts["oscillation"] += 1
        elif "freeze" in skip_reason.lower():
            guard_counts["freeze"] += 1
        elif "cooldown" in skip_reason.lower():
            guard_counts["cooldown"] += 1
    
    for guard_type, count in guard_counts.items():
        lines.append(f'guard_triggers_total{{type="{guard_type}"}} {count}')
    
    # Tuner activity
    for idx, iter_entry in enumerate(tuning_iters, start=1):
        changed_keys = iter_entry.get("changed_keys", [])
        lines.append(f'tuner_keys_changed_total{{iteration="{idx}"}} {len(changed_keys)}')
    
    # Last-8 summary metrics (harmonic mean, trend indicators)
    if len(summaries) >= 8:
        last_8 = summaries[-8:]
        
        # Harmonic mean for maker_taker
        mt_values = [s.get("summary", {}).get("maker_taker_ratio", 0) for s in last_8]
        mt_values = [v for v in mt_values if v > 0]
        
        if mt_values:
            hmean = len(mt_values) / sum(1.0 / v for v in mt_values)
            lines.append(f'maker_taker_ratio_hmean{{window="8"}} {hmean:.4f}')
        
        # Risk/latency averages
        risk_values = [s.get("summary", {}).get("risk_ratio", 0) for s in last_8]
        p95_values = [s.get("summary", {}).get("p95_latency_ms", 0) for s in last_8]
        
        if risk_values:
            risk_avg = sum(risk_values) / len(risk_values)
            lines.append(f'risk_ratio_mean{{window="8"}} {risk_avg:.4f}')
        
        if p95_values:
            p95_max = max(p95_values)
            p95_avg = sum(p95_values) / len(p95_values)
            lines.append(f'p95_latency_ms_max{{window="8"}} {p95_max:.1f}')
            lines.append(f'p95_latency_ms_mean{{window="8"}} {p95_avg:.1f}')
    
    # Partial freeze indicator (from tuning report metadata)
    partial_freeze_active = 0  # Would need to track this in tuning report
    lines.append(f'partial_freeze_active {partial_freeze_active}')
    
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Export warm-up metrics for Prometheus")
    parser.add_argument("--path", type=Path, required=True,
                        help="Path to soak directory (contains ITER_SUMMARY_*.json)")
    parser.add_argument("--output", type=Path, required=True,
                        help="Output file for Prometheus metrics (.prom)")
    
    args = parser.parse_args()
    
    if not args.path.exists():
        print(f"[ERROR] Soak directory not found: {args.path}", file=sys.stderr)
        sys.exit(1)
    
    print(f"[INFO] Loading summaries from: {args.path}")
    summaries = load_iter_summaries(args.path)
    
    if not summaries:
        print("[ERROR] No ITER_SUMMARY files found", file=sys.stderr)
        sys.exit(1)
    
    print(f"[INFO] Loaded {len(summaries)} iteration summaries")
    
    print(f"[INFO] Loading tuning report...")
    tuning = load_tuning_report(args.path)
    
    print(f"[INFO] Exporting metrics to: {args.output}")
    metrics_text = export_warmup_metrics(summaries, tuning)
    
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(metrics_text, encoding='utf-8')
    
    print(f"[OK] Metrics exported successfully")
    print(f"[OK] Total lines: {len(metrics_text.splitlines())}")


if __name__ == "__main__":
    main()


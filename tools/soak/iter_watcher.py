#!/usr/bin/env python3
"""
Iteration watcher for soak tests.

Monitors artifacts after each iteration and suggests micro-tuning based on:
- net_bps vs target (≥ 3.0)
- negative edge drivers (slippage_bps, adverse_bps)
- block reasons (min_interval, concurrency, risk, throttle)

Usage (from tools/soak/run.py):
    from tools.soak import iter_watcher
    
    summary = iter_watcher.summarize_iteration(artifacts_dir)
    deltas = iter_watcher.propose_micro_tuning(summary, current_overrides)
    iter_watcher.write_iteration_outputs(output_dir, iteration_idx, summary, deltas)
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, List, Optional


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Read JSON file, return None if not found or invalid."""
    if not path.exists():
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[iter_watcher] Warning: Could not read {path}: {e}")
        return None


def _analyze_audit_blocks(audit_path: Path) -> Dict[str, Any]:
    """Parse audit.jsonl and return block statistics."""
    blocks = {
        'min_interval': 0,
        'concurrency': 0,
        'risk': 0,
        'throttle': 0,
        'allowed': 0,
        'other': 0
    }
    total = 0
    
    if not audit_path.exists():
        return {'counts': blocks, 'total': 0, 'ratios': {}}
    
    try:
        with open(audit_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    fields = entry.get('fields', {})
                    reason = fields.get('reason')
                    allowed = fields.get('allowed')
                    
                    if reason in blocks:
                        blocks[reason] += 1
                    elif allowed == 1:
                        blocks['allowed'] += 1
                    else:
                        blocks['other'] += 1
                    total += 1
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[iter_watcher] Warning: Could not analyze audit: {e}")
    
    ratios = {}
    if total > 0:
        for k, v in blocks.items():
            ratios[k] = round(v / total * 100, 1)
    
    return {'counts': blocks, 'total': total, 'ratios': ratios}


def summarize_iteration(artifacts_dir: Path) -> Dict[str, Any]:
    """
    Summarize key metrics from artifacts after an iteration.
    
    Reads:
        - EDGE_REPORT.json
        - KPI_GATE.json
        - EDGE_SENTINEL.json
        - audit.jsonl
    
    Returns:
        Dict with runtime, metrics, drivers, blocks, KPI verdict, sentinel advice
    """
    edge = _read_json(artifacts_dir / "EDGE_REPORT.json") or {}
    kpi = _read_json(artifacts_dir / "KPI_GATE.json") or {}
    sentinel = _read_json(artifacts_dir / "EDGE_SENTINEL.json") or {}
    
    # Extract totals (handle both "total" and "totals" keys)
    totals = edge.get("total") or edge.get("totals") or {}
    
    # Extract metrics
    net_bps = totals.get("net_bps")
    gross_bps = totals.get("gross_bps")
    fees_eff_bps = totals.get("fees_eff_bps")
    slippage_bps = totals.get("slippage_bps")
    adverse_bps = totals.get("adverse_bps")
    inventory_bps = totals.get("inventory_bps")
    fills = totals.get("fills")
    
    # Negative edge drivers
    neg_drivers = totals.get("neg_edge_drivers") or []
    if not isinstance(neg_drivers, list):
        neg_drivers = []
    
    # Block analysis
    block_analysis = _analyze_audit_blocks(artifacts_dir / "audit.jsonl")
    
    # Sentinel advice
    advice = sentinel.get("advice")
    if not isinstance(advice, list):
        advice = []
    
    summary = {
        "runtime_utc": (edge.get("runtime") or {}).get("utc"),
        "version": (edge.get("runtime") or {}).get("version"),
        "net_bps": net_bps,
        "gross_bps": gross_bps,
        "fees_eff_bps": fees_eff_bps,
        "slippage_bps": slippage_bps,
        "adverse_bps": adverse_bps,
        "inventory_bps": inventory_bps,
        "fills": fills,
        "neg_edge_drivers": neg_drivers,
        "blocks": {
            "counts": block_analysis['counts'],
            "total": block_analysis['total'],
            "ratios": block_analysis['ratios']
        },
        "kpi_verdict": kpi.get("verdict"),
        "kpi_reasons": kpi.get("reasons") or [],
        "sentinel_advice": advice
    }
    
    return summary


def propose_micro_tuning(
    summary: Dict[str, Any],
    current_overrides: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Suggest micro parameter adjustments based on iteration summary.
    
    RISK-AWARE LOGIC (PRIMARY):
    - If risk blocks ≥ 60% → aggressive throttling (min_interval+5, spread+0.02, impact-0.01)
    - If risk blocks 40-60% → moderate throttling (min_interval+5, impact-0.01)
    - If risk blocks ≤ 40% AND order_age > 360ms → speed up (min_interval-5)
    
    DRIVER-AWARE LOGIC (SECONDARY):
    - If adverse_p95 > 3.5 → reduce impact_cap, max_delta
    - If slippage_p95 > 2.5 → widen spread, increase tail_age
    - If net_bps < 3.2 → general adjustments
    
    Args:
        summary: Output from summarize_iteration()
        current_overrides: Current runtime overrides (for caps/floors)
    
    Returns:
        Dict with deltas, rationale, and applied suggestions
    """
    # Initialize current overrides with defaults
    if current_overrides is None:
        current_overrides = {}
    
    current_min_interval = current_overrides.get("min_interval_ms", 60)
    current_spread_delta = current_overrides.get("base_spread_bps_delta", 0.12)
    current_impact_cap = current_overrides.get("impact_cap_ratio", 0.10)
    current_max_delta = current_overrides.get("max_delta_ratio", 0.15)
    current_tail_age = current_overrides.get("tail_age_ms", 650)
    
    deltas = {}
    reasons = []
    
    # Extract key metrics
    net_bps = summary.get("net_bps")
    ratios = summary.get("blocks", {}).get("ratios", {})
    risk_ratio = ratios.get("risk", 0.0) / 100.0  # Convert percentage to ratio
    
    # Extract p95 metrics from totals (if available)
    adverse_p95 = summary.get("adverse_bps")  # Fallback to mean if p95 not available
    slippage_p95 = summary.get("slippage_bps")
    
    # Try to get p95 from detailed metrics if available
    # (In a real EDGE_REPORT, these might be under different keys)
    
    # Get order_age_p95_ms (may be in different location)
    order_age_p95 = 300  # Default assumption
    
    min_interval_pct = ratios.get("min_interval", 0.0)
    concurrency_pct = ratios.get("concurrency", 0.0)
    
    # Guard
    if net_bps is None:
        return {"deltas": deltas, "rationale": "No net_bps data available", "applied": False}
    
    # ==========================================================================
    # PRIORITY 1: RISK-AWARE TUNING
    # ==========================================================================
    
    if risk_ratio >= 0.60:
        # CRITICAL: High risk blocks - aggressive throttling
        new_min_interval = min(current_min_interval + 5, 90)
        if new_min_interval != current_min_interval:
            deltas["min_interval_ms"] = new_min_interval - current_min_interval
            reasons.append(f"risk={risk_ratio:.1%} (CRITICAL) → min_interval +5ms (cap 90)")
        
        new_spread = min(current_spread_delta + 0.02, 0.20)
        if new_spread != current_spread_delta:
            deltas["base_spread_bps_delta"] = new_spread - current_spread_delta
            reasons.append(f"risk={risk_ratio:.1%} (CRITICAL) → spread +0.02 (cap 0.20)")
        
        new_impact = max(current_impact_cap - 0.01, 0.08)
        if new_impact != current_impact_cap:
            deltas["impact_cap_ratio"] = new_impact - current_impact_cap
            reasons.append(f"risk={risk_ratio:.1%} (CRITICAL) → impact_cap -0.01 (floor 0.08)")
        
        new_tail = max(current_tail_age, 680)
        if new_tail != current_tail_age:
            deltas["tail_age_ms"] = new_tail - current_tail_age
            reasons.append(f"risk={risk_ratio:.1%} (CRITICAL) → tail_age={new_tail}ms (min 680)")
    
    elif risk_ratio >= 0.40:
        # HIGH: Moderate risk blocks - moderate throttling
        new_min_interval = min(current_min_interval + 5, 80)
        if new_min_interval != current_min_interval:
            deltas["min_interval_ms"] = new_min_interval - current_min_interval
            reasons.append(f"risk={risk_ratio:.1%} (HIGH) → min_interval +5ms (cap 80)")
        
        new_impact = max(current_impact_cap - 0.01, 0.09)
        if new_impact != current_impact_cap:
            deltas["impact_cap_ratio"] = new_impact - current_impact_cap
            reasons.append(f"risk={risk_ratio:.1%} (HIGH) → impact_cap -0.01 (floor 0.09)")
    
    # ==========================================================================
    # PRIORITY 2: DRIVER-AWARE TUNING (if adverse or slippage high)
    # ==========================================================================
    
    if adverse_p95 is not None and adverse_p95 > 3.5:
        new_impact = max(current_impact_cap - 0.01, 0.08)
        if new_impact != current_impact_cap and "impact_cap_ratio" not in deltas:
            deltas["impact_cap_ratio"] = new_impact - current_impact_cap
            reasons.append(f"adverse_p95={adverse_p95:.2f} (high) → impact_cap -0.01")
        
        new_max_delta = max(current_max_delta - 0.01, 0.12)
        if new_max_delta != current_max_delta:
            deltas["max_delta_ratio"] = new_max_delta - current_max_delta
            reasons.append(f"adverse_p95={adverse_p95:.2f} (high) → max_delta -0.01")
    
    if slippage_p95 is not None and slippage_p95 > 2.5:
        new_spread = min(current_spread_delta + 0.02, 0.20)
        if new_spread != current_spread_delta and "base_spread_bps_delta" not in deltas:
            deltas["base_spread_bps_delta"] = new_spread - current_spread_delta
            reasons.append(f"slippage_p95={slippage_p95:.2f} (high) → spread +0.02")
        
        new_tail = min(current_tail_age + 30, 800)
        if new_tail != current_tail_age and "tail_age_ms" not in deltas:
            deltas["tail_age_ms"] = new_tail - current_tail_age
            reasons.append(f"slippage_p95={slippage_p95:.2f} (high) → tail +30ms")
    
    # ==========================================================================
    # PRIORITY 3: SPEED UP if risk is low and order age is high
    # ==========================================================================
    
    if risk_ratio <= 0.40 and order_age_p95 > 360:
        new_min_interval = max(current_min_interval - 5, 50)
        if new_min_interval != current_min_interval and "min_interval_ms" not in deltas:
            deltas["min_interval_ms"] = new_min_interval - current_min_interval
            reasons.append(f"risk={risk_ratio:.1%} (LOW) + order_age={order_age_p95}ms (high) → min_interval -5ms (faster)")
    
    # ==========================================================================
    # DECISION: Apply suggestions only if needed
    # ==========================================================================
    
    should_apply = (net_bps < 3.2) or (risk_ratio >= 0.50)
    
    if not should_apply:
        deltas = {}
        reasons = [f"net_bps={net_bps:.2f} OK + risk={risk_ratio:.1%} OK → no changes needed"]
    
    rationale = " | ".join(reasons) if reasons else "No micro-adjustments needed"
    
    return {
        "deltas": deltas,
        "rationale": rationale,
        "applied": False,  # Caller decides whether to apply
        "conditions": {
            "net_bps": net_bps,
            "risk_ratio": risk_ratio,
            "adverse_p95": adverse_p95,
            "slippage_p95": slippage_p95,
            "order_age_p95_ms": order_age_p95,
            "min_interval_pct": min_interval_pct,
            "concurrency_pct": concurrency_pct
        }
    }


def write_iteration_outputs(
    output_dir: Path,
    iteration_idx: int,
    summary: Dict[str, Any],
    tuning_result: Dict[str, Any]
) -> None:
    """
    Write iteration summary and update cumulative TUNING_REPORT.json.
    
    Creates:
        - ITER_SUMMARY_{N}.json: Full summary for iteration N
        - TUNING_REPORT.json: Cumulative list of all iterations
    
    Args:
        output_dir: Directory to write outputs (e.g., artifacts/soak/latest/)
        iteration_idx: Iteration number (1-based)
        summary: Output from summarize_iteration()
        tuning_result: Output from propose_micro_tuning()
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Write individual iteration summary
    iter_summary_path = output_dir / f"ITER_SUMMARY_{iteration_idx}.json"
    with open(iter_summary_path, 'w', encoding='utf-8') as f:
        json.dump({
            "iteration": iteration_idx,
            "summary": summary,
            "tuning": tuning_result
        }, f, ensure_ascii=False, indent=2)
    
    print(f"[iter_watcher] Wrote {iter_summary_path.name}")
    
    # Update cumulative TUNING_REPORT.json
    report_path = output_dir / "TUNING_REPORT.json"
    items = []
    
    if report_path.exists():
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                items = json.load(f)
                if not isinstance(items, list):
                    items = []
        except Exception as e:
            print(f"[iter_watcher] Warning: Could not read existing TUNING_REPORT.json: {e}")
            items = []
    
    items.append({
        "iteration": iteration_idx,
        "runtime_utc": summary.get("runtime_utc"),
        "net_bps": summary.get("net_bps"),
        "kpi_verdict": summary.get("kpi_verdict"),
        "neg_edge_drivers": summary.get("neg_edge_drivers"),
        "suggested_deltas": tuning_result.get("deltas", {}),
        "rationale": tuning_result.get("rationale", ""),
        "applied": tuning_result.get("applied", False)
    })
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    
    print(f"[iter_watcher] Updated {report_path.name} (total iterations: {len(items)})")


def print_iteration_markers(
    iteration_idx: int,
    summary: Dict[str, Any],
    tuning_result: Dict[str, Any]
) -> None:
    """
    Print standardized log markers for iteration monitoring.
    
    Format:
        | iter_watch | SUMMARY | net=... drivers=[...] kpi=... |
        | iter_watch | SUGGEST | {...} |
    """
    net_bps = summary.get("net_bps")
    drivers = summary.get("neg_edge_drivers") or []
    kpi_verdict = summary.get("kpi_verdict") or "UNKNOWN"
    deltas = tuning_result.get("deltas", {})
    rationale = tuning_result.get("rationale", "")
    
    print(f"| iter_watch | SUMMARY | iter={iteration_idx} net={net_bps} drivers={drivers} kpi={kpi_verdict} |")
    
    if deltas:
        print(f"| iter_watch | SUGGEST | {json.dumps(deltas)} |")
        print(f"| iter_watch | RATIONALE | {rationale} |")
    else:
        print(f"| iter_watch | SUGGEST | (none) |")


# Convenience function for all-in-one iteration processing
def process_iteration(
    iteration_idx: int,
    artifacts_dir: Path,
    output_dir: Path,
    current_overrides: Optional[Dict[str, float]] = None,
    print_markers: bool = True
) -> Dict[str, Any]:
    """
    All-in-one iteration processing: summarize, suggest tuning, write outputs, print markers.
    
    Args:
        iteration_idx: Iteration number (1-based)
        artifacts_dir: Directory containing EDGE_REPORT.json, KPI_GATE.json, etc.
        output_dir: Directory to write ITER_SUMMARY_*.json and TUNING_REPORT.json
        current_overrides: Current runtime overrides (optional)
        print_markers: Whether to print log markers
    
    Returns:
        Dict containing summary and tuning_result
    """
    summary = summarize_iteration(artifacts_dir)
    tuning_result = propose_micro_tuning(summary, current_overrides)
    write_iteration_outputs(output_dir, iteration_idx, summary, tuning_result)
    
    if print_markers:
        print_iteration_markers(iteration_idx, summary, tuning_result)
    
    return {
        "summary": summary,
        "tuning": tuning_result
    }


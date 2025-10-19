#!/usr/bin/env python3
"""
Post-soak edge fix analyzer.

Reads artifacts after 3h soak and generates AUDIT_EDGE_FIX.md with:
- Before vs After comparison
- Block breakdown analysis
- KPI gate status
- Micro-tuning recommendations if net_bps < 3.0

Usage:
    python -m tools.soak.analyze_edge_fix
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple


def read_json(path: Path) -> Dict[str, Any]:
    """Read JSON file, return empty dict if not found."""
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not read {path}: {e}", file=sys.stderr)
        return {}


def analyze_blocks(audit_path: Path) -> Dict[str, Any]:
    """Analyze block reasons from audit.jsonl."""
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
        return {'blocks': blocks, 'total': 0, 'ratios': {}}
    
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
        print(f"Warning: Could not analyze audit: {e}", file=sys.stderr)
    
    ratios = {}
    if total > 0:
        for k, v in blocks.items():
            ratios[k] = round(v / total * 100, 1)
    
    return {'blocks': blocks, 'total': total, 'ratios': ratios}


def suggest_micro_tuning(
    current_params: Dict[str, float],
    edge_report: Dict[str, Any],
    blocks: Dict[str, Any]
) -> Tuple[Dict[str, float], str]:
    """
    Suggest micro parameter adjustments if net_bps < 3.0.
    
    Returns:
        (delta_params, rationale)
    """
    total = edge_report.get('total', {})
    net_bps = total.get('net_bps', 0.0)
    adverse_bps = total.get('adverse_bps', 0.0)
    slippage_bps = total.get('slippage_bps', 0.0)
    
    ratios = blocks.get('ratios', {})
    min_interval_pct = ratios.get('min_interval', 0.0)
    concurrency_pct = ratios.get('concurrency', 0.0)
    
    delta = {}
    reasons = []
    
    # If adverse is still high (> 10), reduce aggression further
    if adverse_bps > 10:
        delta['impact_cap_ratio'] = -0.01
        delta['max_delta_ratio'] = -0.01
        reasons.append(f"adverse_bps={adverse_bps:.1f} (high) → lower impact_cap & max_delta by -0.01")
    
    # If net_bps is close (2.5-3.0), widen spread slightly
    if 2.5 <= net_bps < 3.0:
        delta['base_spread_bps_delta'] = 0.02
        reasons.append(f"net_bps={net_bps:.2f} (close) → widen spread by +0.02 to capture more gross")
    
    # If net_bps is very low (< 2.5), more aggressive spread widening
    if net_bps < 2.5:
        delta['base_spread_bps_delta'] = 0.03
        reasons.append(f"net_bps={net_bps:.2f} (low) → widen spread by +0.03")
    
    # If slippage is positive (cost), reduce churn
    if slippage_bps > 1.0:
        delta['tail_age_ms'] = 50
        delta['min_interval_ms'] = 10
        reasons.append(f"slippage_bps={slippage_bps:.2f} (cost) → increase tail_age & min_interval")
    
    # If blocking is high, adjust pacing
    if min_interval_pct > 25:
        delta['min_interval_ms'] = 15
        reasons.append(f"min_interval blocks={min_interval_pct:.1f}% (high) → increase by +15ms")
    
    if concurrency_pct > 25:
        delta['replace_rate_per_min'] = -30
        reasons.append(f"concurrency blocks={concurrency_pct:.1f}% (high) → reduce rate by -30")
    
    rationale = " | ".join(reasons) if reasons else "No micro-adjustments needed"
    
    return delta, rationale


def main():
    """Main analysis function."""
    
    # Paths
    artifacts_dir = Path('artifacts/soak/latest/artifacts')
    output_path = Path('artifacts/soak/latest/AUDIT_EDGE_FIX.md')
    
    # Read artifacts
    edge_report = read_json(artifacts_dir / 'EDGE_REPORT.json')
    kpi_gate = read_json(artifacts_dir / 'KPI_GATE.json')
    edge_sentinel = read_json(artifacts_dir / 'EDGE_SENTINEL.json')
    tuning_report = read_json(artifacts_dir / 'TUNING_REPORT.json')
    param_sweep = read_json(artifacts_dir / 'PARAM_SWEEP.json')
    
    # Analyze blocks
    block_analysis = analyze_blocks(artifacts_dir / 'audit.jsonl')
    
    # Read current runtime overrides
    runtime_overrides = read_json(Path('artifacts/soak/runtime_overrides.json'))
    
    # Read baseline (from RUNTIME_RECOMMENDATIONS.json)
    baseline = read_json(Path('artifacts/soak/latest/RUNTIME_RECOMMENDATIONS.json'))
    baseline_drivers = baseline.get('based_on', {}).get('current_drivers', {})
    
    # Extract metrics
    total = edge_report.get('total', {})
    net_bps = total.get('net_bps', 0.0)
    gross_bps = total.get('gross_bps', 0.0)
    adverse_bps = total.get('adverse_bps', 0.0)
    slippage_bps = total.get('slippage_bps', 0.0)
    fees_eff_bps = total.get('fees_eff_bps', 0.0)
    inventory_bps = total.get('inventory_bps', 0.0)
    fills = total.get('fills', 0.0)
    
    # KPI gate
    verdict = kpi_gate.get('verdict', 'UNKNOWN')
    reasons = kpi_gate.get('reasons', [])
    
    # Blocks
    ratios = block_analysis.get('ratios', {})
    
    # Build markdown report
    lines = [
        "# 📊 EDGE FIX AUDIT REPORT",
        "",
        f"**Generated:** {edge_report.get('runtime', {}).get('utc', 'unknown')}",
        f"**KPI Gate:** `{verdict}`",
        "",
        "---",
        "",
        "## 📈 BEFORE vs AFTER",
        "",
        "| Metric | Before (Baseline) | After (This Run) | Δ | Status |",
        "|--------|-------------------|------------------|---|--------|",
        f"| `net_bps` | {baseline_drivers.get('net_bps', 0.0):.2f} | **{net_bps:.2f}** | {net_bps - baseline_drivers.get('net_bps', 0.0):+.2f} | {'✅ PASS' if net_bps >= 3.0 else ('⚠️ WARN' if net_bps >= 2.5 else '❌ FAIL')} |",
        f"| `gross_bps` | {baseline_drivers.get('gross_bps', 10.0):.2f} | {gross_bps:.2f} | {gross_bps - baseline_drivers.get('gross_bps', 10.0):+.2f} | - |",
        f"| `adverse_bps` | {baseline_drivers.get('adverse_bps', 15.83):.2f} | {adverse_bps:.2f} | {adverse_bps - baseline_drivers.get('adverse_bps', 15.83):+.2f} | {'✅' if adverse_bps <= 10 else ('⚠️' if adverse_bps <= 12 else '❌')} |",
        f"| `slippage_bps` | {baseline_drivers.get('slippage_bps', -4.16):.2f} | {slippage_bps:.2f} | {slippage_bps - baseline_drivers.get('slippage_bps', -4.16):+.2f} | {'✅' if slippage_bps < 0 else '⚠️'} |",
        f"| `fees_eff_bps` | {baseline_drivers.get('fees_eff_bps', 0.1):.2f} | {fees_eff_bps:.2f} | {fees_eff_bps - baseline_drivers.get('fees_eff_bps', 0.1):+.2f} | - |",
        f"| `inventory_bps` | {baseline_drivers.get('inventory_bps', 0.01):.2f} | {inventory_bps:.2f} | {inventory_bps - baseline_drivers.get('inventory_bps', 0.01):+.2f} | - |",
        f"| `fills` | {baseline_drivers.get('fills', 6.0):.0f} | {fills:.0f} | {fills - baseline_drivers.get('fills', 6.0):+.0f} | - |",
        "",
        "---",
        "",
        "## 🚦 BLOCK BREAKDOWN",
        "",
        "| Block Reason | Count | Ratio | Status |",
        "|--------------|-------|-------|--------|",
    ]
    
    for reason in ['min_interval', 'concurrency', 'risk', 'throttle', 'allowed', 'other']:
        count = block_analysis['blocks'].get(reason, 0)
        ratio = ratios.get(reason, 0.0)
        status = '✅' if ratio < 25 or reason == 'allowed' else ('⚠️' if ratio < 35 else '❌')
        lines.append(f"| `{reason}` | {count} | {ratio:.1f}% | {status} |")
    
    lines.extend([
        "",
        f"**Total actions:** {block_analysis['total']}",
        "",
        "---",
        "",
        "## 🎯 KPI GATE STATUS",
        "",
        f"**Verdict:** `{verdict}`",
        "",
        "**Reasons:**",
    ])
    
    if reasons:
        for r in reasons:
            lines.append(f"- {r}")
    else:
        lines.append("- (none)")
    
    lines.extend([
        "",
        "---",
        "",
        "## 📊 ACCEPTANCE CRITERIA",
        "",
        "| Criterion | Target | Actual | Status |",
        "|-----------|--------|--------|--------|",
        f"| `net_bps ≥ 3.0` | ≥ 3.0 | {net_bps:.2f} | {'✅ PASS' if net_bps >= 3.0 else '❌ FAIL'} |",
        f"| `adverse_bps ≤ 10` | ≤ 10 | {adverse_bps:.2f} | {'✅ PASS' if adverse_bps <= 10 else ('⚠️ WARN' if adverse_bps <= 12 else '❌ FAIL')} |",
        f"| `KPI_GATE != FAIL` | != FAIL | {verdict} | {'✅ PASS' if verdict != 'FAIL' else '❌ FAIL'} |",
        "",
    ])
    
    # Check if micro-tuning is needed
    if net_bps < 3.0:
        delta, rationale = suggest_micro_tuning(runtime_overrides, edge_report, block_analysis)
        
        lines.extend([
            "---",
            "",
            "## 🔧 NEXT STEP: MICRO-TUNING REQUIRED",
            "",
            f"**Current net_bps:** {net_bps:.2f} (target: ≥ 3.0)",
            "",
            "**Recommended adjustments:**",
            "",
            "```json",
        ])
        
        if delta:
            lines.append("{")
            for i, (k, v) in enumerate(delta.items()):
                comma = "," if i < len(delta) - 1 else ""
                current = runtime_overrides.get(k, 0.0)
                new_val = current + v
                lines.append(f'  "{k}": {new_val}{comma}  // was {current}, Δ={v:+.2f}')
            lines.append("}")
        else:
            lines.append("{}")
        
        lines.extend([
            "```",
            "",
            f"**Rationale:** {rationale}",
            "",
            "**Expected impact:** +0.3 to +0.5 bps",
            "",
            "**Apply with:**",
            "```powershell",
            "# Merge deltas into runtime_overrides.json manually, then re-run:",
            "python -m tools.soak.run --hours 3 --auto-tune",
            "```",
            "",
        ])
    else:
        lines.extend([
            "---",
            "",
            "## ✅ SUCCESS",
            "",
            f"**net_bps = {net_bps:.2f}** meets target (≥ 3.0)",
            "",
            "No further tuning required. Settings are stable.",
            "",
        ])
    
    lines.extend([
        "---",
        "",
        f"**Analysis complete:** {len(lines)} lines generated",
    ])
    
    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"✅ Analysis complete: {output_path}")
    print(f"   net_bps: {net_bps:.2f} (target: ≥ 3.0)")
    print(f"   KPI Gate: {verdict}")
    
    # Exit code based on success
    if net_bps >= 3.0 and verdict != 'FAIL':
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()


#!/usr/bin/env python3
"""Tuning report generator."""
import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any


def _select_candidate(sweep: Dict[str, Any]) -> Dict[str, Any]:
    """
    Select the best candidate from sweep results.
    
    Priority:
    1. Check top3_by_net_bps_safe if available
    2. Otherwise use first result
    
    Args:
        sweep: Sweep dict with 'results' and optional 'top3_by_net_bps_safe'
    
    Returns:
        Selected candidate dict
    """
    top3 = sweep.get('top3_by_net_bps_safe', [])
    if top3:
        return top3[0]
    
    results = sweep.get('results', [])
    if results:
        return results[0]
    
    # Fallback: empty candidate
    return {
        "params": {},
        "metrics_before": {},
        "metrics_after": {},
        "verdict": "HOLD"
    }


def _extract_candidates(sweep: Dict[str, Any], k: int = 3) -> List[Dict[str, Any]]:
    """
    Extract top k candidates from sweep.
    
    Args:
        sweep: Sweep dict with 'results' and optional 'top3_by_net_bps_safe'
        k: Number of candidates to extract
    
    Returns:
        List of candidate dicts (up to k items)
    """
    top3 = sweep.get('top3_by_net_bps_safe', [])
    if top3:
        return top3[:k]
    
    results = sweep.get('results', [])
    return results[:k]


def _render_md(report: Dict[str, Any]) -> str:
    """
    Render report as Markdown (deterministic, stable order).
    
    Args:
        report: Report dict with 'selected', 'candidates', 'runtime'
    
    Returns:
        Markdown string (with trailing newline)
    """
    lines = []
    lines.append("TUNING REPORT\n\n")
    
    selected = report.get('selected')
    if selected:
        lines.append("## Selected Candidate\n\n")
        lines.append(f"**Verdict:** {selected.get('verdict', 'UNKNOWN')}\n\n")
        
        params = selected.get('params', {})
        if params:
            lines.append("**Parameters:**\n")
            for key in sorted(params.keys()):
                lines.append(f"- {key}: {params[key]:.6f}\n")
            lines.append("\n")
        
        mb = selected.get('metrics_before', {})
        ma = selected.get('metrics_after', {})
        if mb or ma:
            lines.append("**Metrics:**\n")
            lines.append(f"- net_bps_before: {mb.get('net_bps', 0):.6f}\n")
            lines.append(f"- net_bps_after: {ma.get('net_bps', 0):.6f}\n")
            lines.append(f"- order_age_p95_ms_after: {ma.get('order_age_p95_ms', 0):.6f}\n")
            lines.append("\n")
    
    candidates = report.get('candidates', [])
    if candidates:
        lines.append("## All Candidates\n\n")
        lines.append("| verdict | max_delta_ratio | impact_cap_ratio | min_interval_ms | tail_age_ms | net_before | net_after | p95_after |\n")
        lines.append("|---------|-----------------|------------------|-----------------|-------------|------------|-----------|------------|\n")
        
        for cand in candidates:
            params = cand.get('params', {})
            mb = cand.get('metrics_before', {})
            ma = cand.get('metrics_after', {})
            verdict = cand.get('verdict', 'UNKNOWN')
            
            lines.append(f"| {verdict} | {params.get('max_delta_ratio', 0):.6f} | {params.get('impact_cap_ratio', 0):.6f} | ")
            lines.append(f"{params.get('min_interval_ms', 0):.6f} | {params.get('tail_age_ms', 0):.6f} | ")
            lines.append(f"{mb.get('net_bps', 0):.6f} | {ma.get('net_bps', 0):.6f} | {ma.get('order_age_p95_ms', 0):.6f} |\n")
    else:
        lines.append("No candidates available.\n")
    
    return "".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tuning Report Generator")
    parser.add_argument("--sweep", default="artifacts/PARAM_SWEEP.json", help="Path to PARAM_SWEEP.json")
    parser.add_argument("--out-json", default="artifacts/TUNING_REPORT.json", help="Output JSON path")
    parser.add_argument("--out-md", default="artifacts/TUNING_REPORT.md", help="Output Markdown path")
    parser.add_argument("--update-golden", action="store_true", help="Update golden file for tests")
    args = parser.parse_args(argv)
    
    # Load sweep data
    sweep_path = Path(args.sweep)
    if not sweep_path.exists():
        # Create minimal fallback
        sweep = {"results": []}
    else:
        with open(sweep_path, 'r', encoding='utf-8') as f:
            sweep = json.load(f)
    
    # Extract selected candidate and top-k candidates
    selected = _select_candidate(sweep)
    candidates = _extract_candidates(sweep, k=3)
    
    # Build report
    utc_iso = os.environ.get('MM_FREEZE_UTC_ISO', datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    report = {
        "candidates": candidates,
        "metrics": {
            "total_candidates": len(sweep.get('results', [])),
            "selected_verdict": selected.get('verdict', 'UNKNOWN')
        },
        "runtime": {
            "utc": utc_iso,
            "version": "0.1.0"
        },
        "selected": selected
    }
    
    # Write JSON output
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, 'w', encoding='utf-8', newline='') as f:
        json.dump(report, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write('\n')
    
    # Write MD output
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    md_content = _render_md(report)
    with open(out_md, 'w', encoding='utf-8', newline='') as f:
        f.write(md_content)
    
    # Update golden files if requested
    if args.update_golden:
        import shutil
        golden_dir = Path("tests/golden")
        golden_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(out_json, golden_dir / "TUNING_REPORT_case1.json")
        shutil.copy(out_md, golden_dir / "TUNING_REPORT_case1.md")
        print(f"[OK] Updated golden files: {golden_dir}/TUNING_REPORT_case1.{{json,md}}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

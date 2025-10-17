#!/usr/bin/env python3
"""
Delta-Apply Verifier Tool.

Verifies that proposed parameter deltas were correctly applied between iterations.
Checks for signature changes, guard activations, skip reasons, and parameter mismatches.

Usage:
    python -m tools.soak.verify_deltas_applied [--path PATH] [--strict] [--json]

Exit codes:
    0 = >=90% full applications (or >=80% with 0 signature_stuck) [--strict: >=95%]
    1 = below threshold or errors
"""

import glob
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


# Float comparison tolerance
FLOAT_TOLERANCE = 1e-9


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON file with error handling."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to load {path}: {e}", file=sys.stderr)
        return None


def _iter_files(base_path: Path) -> List[Path]:
    """Find and sort ITER_SUMMARY_*.json files by iteration number."""
    pattern = str(base_path / "ITER_SUMMARY_*.json")
    files = glob.glob(pattern)
    
    def get_iter_num(fpath: str) -> int:
        match = re.search(r'ITER_SUMMARY_(\d+)\.json', fpath)
        return int(match.group(1)) if match else 0
    
    return sorted([Path(f) for f in files], key=lambda p: get_iter_num(str(p)))


def _load_tuning_report(base_path: Path) -> Optional[Dict[str, Any]]:
    """Load TUNING_REPORT.json."""
    tuning_path = base_path / "TUNING_REPORT.json"
    if not tuning_path.exists():
        print(f"[ERROR] TUNING_REPORT.json not found: {tuning_path}", file=sys.stderr)
        return None
    return _load_json_safe(tuning_path)


def _load_iter_summaries(base_path: Path) -> Dict[int, Dict[str, Any]]:
    """Load all ITER_SUMMARY_*.json files, keyed by iteration number."""
    summaries = {}
    for fpath in _iter_files(base_path):
        data = _load_json_safe(fpath)
        if data:
            # Extract iteration number from filename
            match = re.search(r'ITER_SUMMARY_(\d+)\.json', str(fpath))
            if match:
                iter_num = int(match.group(1))
                summaries[iter_num] = data
    return summaries


def _get_signature(data: Dict[str, Any]) -> str:
    """Extract signature from iteration data."""
    tuning = data.get("tuning", {})
    sig = tuning.get("signature") or tuning.get("state_hash") or "unknown"
    return str(sig)


def _get_runtime_params(data: Dict[str, Any], keys: List[str]) -> Dict[str, float]:
    """
    Extract runtime parameters for specific keys using params mapping.
    
    Args:
        data: Iteration data
        keys: List of parameter keys to extract
    
    Returns:
        Dict mapping flat keys to their values (using nested path resolution)
    """
    try:
        from tools.soak import params as P
        
        # Find runtime dict (priority: runtime_overrides > runtime > config)
        runtime = data.get("runtime_overrides") or data.get("runtime") or data.get("config", {})
        
        if not runtime:
            return {}
        
        # Use params module to resolve nested paths
        result = {}
        for key in keys:
            val = P.get_from_runtime(runtime, key)
            if val is not None:
                result[key] = float(val)
        
        return result
    
    except ImportError:
        # Fallback: try flat extraction (won't handle nested properly)
        runtime = data.get("runtime_overrides", data.get("runtime", {}))
        params = {}
        for key in keys:
            val = runtime.get(key)
            if isinstance(val, (int, float)):
                params[key] = float(val)
        
        return params


def _compare_params(
    proposed: Dict[str, float],
    observed: Dict[str, float]
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Compare proposed deltas with observed parameters.
    
    Returns:
        (all_match: bool, mismatches: list of dicts)
    """
    mismatches = []
    
    for param, proposed_val in proposed.items():
        observed_val = observed.get(param)
        
        if observed_val is None:
            mismatches.append({
                "param": param,
                "proposed": proposed_val,
                "observed": None,
                "reason": "parameter not found in runtime"
            })
            continue
        
        # Float comparison with tolerance
        diff = abs(proposed_val - observed_val)
        if diff > FLOAT_TOLERANCE:
            mismatches.append({
                "param": param,
                "proposed": proposed_val,
                "observed": observed_val,
                "delta": diff,
            })
    
    return len(mismatches) == 0, mismatches


def _get_guard_reasons(guards: Dict[str, bool]) -> List[str]:
    """Extract active guard reasons."""
    reasons = []
    if guards.get("cooldown_active"):
        reasons.append("cooldown_active")
    if guards.get("velocity_violation"):
        reasons.append("velocity_violation")
    if guards.get("oscillation_detected"):
        reasons.append("oscillation_detected")
    if guards.get("freeze_triggered"):
        reasons.append("freeze_triggered")
    return reasons


def _analyze_iteration_pair(
    iter_prev: int,
    data_prev: Dict[str, Any],
    iter_curr: int,
    data_curr: Dict[str, Any],
    tuning_iter_prev: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Analyze a pair of iterations (i-1 → i) for delta application.
    
    Returns dict with analysis results.
    """
    result = {
        "iter_prev": iter_prev,
        "iter_curr": iter_curr,
        "proposed_deltas": {},
        "applied": False,
        "signature_changed": False,
        "signature_stuck": False,
        "params_match": "N/A",
        "guards": {},
        "guard_reasons": [],
        "mismatches": [],
        "reason": "",
    }
    
    # Get proposed deltas from tuning report (iteration i-1)
    if tuning_iter_prev:
        # Try both "proposed_deltas" and "suggested_deltas" keys
        result["proposed_deltas"] = (
            tuning_iter_prev.get("proposed_deltas") or
            tuning_iter_prev.get("suggested_deltas") or
            {}
        )
        result["applied"] = tuning_iter_prev.get("applied", False)
        
        # Get guards from tuning report
        result["guards"] = {
            "cooldown_active": tuning_iter_prev.get("cooldown_active", False),
            "velocity_violation": tuning_iter_prev.get("velocity_violation", False),
            "oscillation_detected": tuning_iter_prev.get("oscillation_detected", False),
            "freeze_triggered": tuning_iter_prev.get("freeze_triggered", False),
        }
        result["guard_reasons"] = _get_guard_reasons(result["guards"])
    
    # Check if tuning.applied is also in ITER_SUMMARY (fallback)
    if not result["applied"]:
        tuning_prev = data_prev.get("tuning", {})
        result["applied"] = tuning_prev.get("applied", False)
    
    # Check signature change
    sig_prev = _get_signature(data_prev)
    sig_curr = _get_signature(data_curr)
    result["signature_changed"] = sig_prev != sig_curr
    
    # Check for signature_stuck (proposed but not changed)
    if result["proposed_deltas"] and result["applied"] and not result["signature_changed"]:
        result["signature_stuck"] = True
        result["reason"] = "signature_stuck"
    
    # If no deltas proposed, skip parameter check
    if not result["proposed_deltas"]:
        result["params_match"] = "N/A"
        result["reason"] = "no_deltas_proposed"
        return result
    
    # Compare proposed vs observed parameters
    # Pass proposed keys to get_runtime_params for proper nested resolution
    proposed_keys = list(result["proposed_deltas"].keys())
    params_curr = _get_runtime_params(data_curr, proposed_keys)
    all_match, mismatches = _compare_params(result["proposed_deltas"], params_curr)
    
    result["mismatches"] = mismatches
    
    # Check skip_reason (if applied=false with explicit skip reason → partial_ok)
    skip_reason = {}
    if tuning_iter_prev:
        skip_reason = tuning_iter_prev.get("skip_reason", {})
    
    # If not applied but has skip_reason → consider partial_ok
    if not result["applied"] and skip_reason:
        any_guard = (
            skip_reason.get("cooldown") or
            skip_reason.get("velocity") or
            skip_reason.get("oscillation") or
            skip_reason.get("freeze") or
            skip_reason.get("no_op")
        )
        
        if any_guard:
            result["params_match"] = "partial_ok"
            result["reason"] = f"skipped: {skip_reason.get('note', 'guard active')}"
            return result
    
    # Determine match status
    if all_match:
        result["params_match"] = "Y"
        result["reason"] = "full_apply"
    elif result["guard_reasons"]:
        # Guards active → partial application acceptable
        result["params_match"] = "partial_ok"
        result["reason"] = f"partial_apply_guards: {', '.join(result['guard_reasons'])}"
    else:
        result["params_match"] = "N"
        result["reason"] = "mismatch_no_guards"
    
    return result


def _generate_report(
    analyses: List[Dict[str, Any]],
    output_path: Path
):
    """Generate Markdown report."""
    lines = [
        "# Delta-Apply Verification Report",
        "",
        "This report verifies that proposed parameter deltas were correctly applied between iterations.",
        "",
        "## Summary Table",
        "",
        "| Iter (i-1 → i) | Proposed Keys | Applied | Guards | Sig Changed | Params Match | Reason |",
        "|----------------|---------------|---------|--------|-------------|--------------|--------|",
    ]
    
    for analysis in analyses:
        iter_prev = analysis["iter_prev"]
        iter_curr = analysis["iter_curr"]
        proposed_keys = ", ".join(analysis["proposed_deltas"].keys()) or "none"
        applied = "Y" if analysis["applied"] else "N"
        guards = ", ".join(analysis["guard_reasons"]) or "none"
        sig_changed = "Y" if analysis["signature_changed"] else "N"
        params_match = analysis["params_match"]
        reason = analysis["reason"]
        
        lines.append(
            f"| {iter_prev} → {iter_curr} | {proposed_keys} | {applied} | {guards} | "
            f"{sig_changed} | {params_match} | {reason} |"
        )
    
    # Calculate metrics
    total = len(analyses)
    proposed_count = sum(1 for a in analyses if a["proposed_deltas"])
    full_apply = sum(1 for a in analyses if a["params_match"] == "Y")
    partial_ok = sum(1 for a in analyses if a["params_match"] == "partial_ok")
    fail = sum(1 for a in analyses if a["params_match"] == "N")
    signature_stuck = sum(1 for a in analyses if a["signature_stuck"])
    
    # Calculate ratio (full / total proposed)
    full_apply_ratio = (full_apply / proposed_count) if proposed_count > 0 else 0
    full_apply_pct = full_apply_ratio * 100
    partial_ok_pct = (partial_ok / proposed_count * 100) if proposed_count > 0 else 0
    fail_pct = (fail / proposed_count * 100) if proposed_count > 0 else 0
    
    lines.extend([
        "",
        "## Metrics",
        "",
        f"- **Total iteration pairs:** {total}",
        f"- **Pairs with proposed deltas:** {proposed_count}",
        f"- **Full applications:** {full_apply} ({full_apply_pct:.1f}%)",
        f"- **Partial OK (skipped with reason):** {partial_ok} ({partial_ok_pct:.1f}%)",
        f"- **Failed applications:** {fail} ({fail_pct:.1f}%)",
        f"- **Signature stuck events:** {signature_stuck}",
        f"- **Full apply ratio:** {full_apply_ratio:.3f}",
        "",
    ])
    
    # Detailed mismatches
    if any(a["mismatches"] for a in analyses):
        lines.extend([
            "## Detailed Mismatches",
            "",
        ])
        
        for analysis in analyses:
            if analysis["mismatches"]:
                iter_prev = analysis["iter_prev"]
                iter_curr = analysis["iter_curr"]
                lines.append(f"### Iteration {iter_prev} → {iter_curr}")
                lines.append("")
                lines.append("| Parameter | Proposed | Observed | Delta | Reason |")
                lines.append("|-----------|----------|----------|-------|--------|")
                
                for mm in analysis["mismatches"]:
                    param = mm["param"]
                    proposed = mm.get("proposed", "N/A")
                    observed = mm.get("observed", "N/A")
                    delta = mm.get("delta", "N/A")
                    reason = mm.get("reason", "value mismatch")
                    
                    if isinstance(proposed, float):
                        proposed = f"{proposed:.6f}"
                    if isinstance(observed, float):
                        observed = f"{observed:.6f}"
                    if isinstance(delta, float):
                        delta = f"{delta:.6f}"
                    
                    lines.append(f"| {param} | {proposed} | {observed} | {delta} | {reason} |")
                
                lines.append("")
    
    # Problematic parameters
    param_failures = {}
    for analysis in analyses:
        for mm in analysis["mismatches"]:
            param = mm["param"]
            param_failures[param] = param_failures.get(param, 0) + 1
    
    if param_failures:
        lines.extend([
            "## Problematic Parameters",
            "",
            "Parameters with most mismatches:",
            "",
        ])
        
        sorted_params = sorted(param_failures.items(), key=lambda x: x[1], reverse=True)
        for param, count in sorted_params:
            lines.append(f"- **{param}:** {count} mismatches")
        
        lines.append("")
    
    # Final verdict
    lines.extend([
        "## Verdict",
        "",
    ])
    
    if full_apply_pct >= 90 or (full_apply_pct >= 80 and signature_stuck == 0):
        lines.append(f"✅ **PASS** - {full_apply_pct:.1f}% full applications (threshold: >=90% or >=80% with no signature_stuck)")
    else:
        lines.append(f"❌ **FAIL** - {full_apply_pct:.1f}% full applications (threshold: >=90% or >=80% with no signature_stuck)")
    
    # Write report
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def verify_deltas(base_path: Path, strict: bool = False) -> Tuple[int, Dict[str, Any]]:
    """
    Verify delta applications.
    
    Returns:
        (exit_code, metrics_dict)
    """
    # Load data
    tuning_report = _load_tuning_report(base_path)
    if not tuning_report:
        return 1
    
    iter_summaries = _load_iter_summaries(base_path)
    if not iter_summaries:
        print("[ERROR] No ITER_SUMMARY_*.json files found", file=sys.stderr)
        return 1
    
    # Build iteration mapping from tuning report
    tuning_iters = {}
    # Handle both dict with "iterations" key and direct list
    if isinstance(tuning_report, list):
        iter_list = tuning_report
    else:
        iter_list = tuning_report.get("iterations", [])
    
    for iter_data in iter_list:
        iter_num = iter_data.get("iteration")
        if iter_num is not None:
            tuning_iters[iter_num] = iter_data
    
    # Analyze each iteration pair
    analyses = []
    sorted_iters = sorted(iter_summaries.keys())
    
    for i in range(len(sorted_iters) - 1):
        iter_prev = sorted_iters[i]
        iter_curr = sorted_iters[i + 1]
        
        data_prev = iter_summaries[iter_prev]
        data_curr = iter_summaries[iter_curr]
        tuning_iter_prev = tuning_iters.get(iter_prev)
        
        analysis = _analyze_iteration_pair(
            iter_prev, data_prev,
            iter_curr, data_curr,
            tuning_iter_prev
        )
        
        analyses.append(analysis)
    
    # Generate report
    output_path = base_path / "DELTA_VERIFY_REPORT.md"
    _generate_report(analyses, output_path)
    
    print(f"[OK] Report written to: {output_path}", file=sys.stderr)
    
    # Calculate metrics for exit code
    proposed_count = sum(1 for a in analyses if a["proposed_deltas"])
    if proposed_count == 0:
        print("[WARN] No deltas proposed in any iteration", file=sys.stderr)
        metrics = {
            "full_apply_ratio": 0.0,
            "full_apply_count": 0,
            "partial_ok_count": 0,
            "fail_count": 0,
            "signature_stuck_count": 0,
            "proposed_count": 0,
        }
        return 0, metrics  # Nothing to verify
    
    full_apply = sum(1 for a in analyses if a["params_match"] == "Y")
    partial_ok = sum(1 for a in analyses if a["params_match"] == "partial_ok")
    fail = sum(1 for a in analyses if a["params_match"] == "N")
    signature_stuck = sum(1 for a in analyses if a["signature_stuck"])
    
    full_apply_ratio = full_apply / proposed_count
    full_apply_pct = full_apply_ratio * 100
    
    # Metrics dict for JSON output
    metrics = {
        "full_apply_ratio": round(full_apply_ratio, 3),
        "full_apply_count": full_apply,
        "partial_ok_count": partial_ok,
        "fail_count": fail,
        "signature_stuck_count": signature_stuck,
        "proposed_count": proposed_count,
    }
    
    # Determine threshold
    threshold = 95.0 if strict else 90.0
    
    print(f"\nVerification Summary:", file=sys.stderr)
    print(f"  Full applications: {full_apply}/{proposed_count} ({full_apply_pct:.1f}%)", file=sys.stderr)
    print(f"  Partial OK: {partial_ok}", file=sys.stderr)
    print(f"  Failed: {fail}", file=sys.stderr)
    print(f"  Signature stuck: {signature_stuck}", file=sys.stderr)
    print(f"  Threshold: >={threshold}%", file=sys.stderr)
    
    # Exit code logic
    if strict:
        if full_apply_pct >= threshold:
            print(f"\n✅ PASS (strict mode: >={threshold}%)", file=sys.stderr)
            return 0, metrics
        else:
            print(f"\n❌ FAIL (strict mode: <{threshold}%)", file=sys.stderr)
            return 1, metrics
    else:
        if full_apply_pct >= threshold or (full_apply_pct >= 80 and signature_stuck == 0):
            print(f"\n✅ PASS", file=sys.stderr)
            return 0, metrics
        else:
            print(f"\n❌ FAIL", file=sys.stderr)
            return 1, metrics


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Delta-Apply Verifier Tool"
    )
    parser.add_argument(
        "--path",
        type=str,
        default="artifacts/soak/latest",
        help="Path to soak/latest directory (default: artifacts/soak/latest)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Use strict threshold (>=95%% instead of >=90%%)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output metrics as JSON to stdout (for CI/CD integration)",
    )
    
    args = parser.parse_args()
    
    base_path = Path(args.path).resolve()
    
    if not base_path.exists():
        print(f"[ERROR] Path does not exist: {base_path}", file=sys.stderr)
        sys.exit(1)
    
    exit_code, metrics = verify_deltas(base_path, strict=args.strict)
    
    # Output JSON if requested
    if args.json:
        print(json.dumps(metrics, indent=2))
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()


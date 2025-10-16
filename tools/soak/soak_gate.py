#!/usr/bin/env python3
"""
Unified Soak Gate Orchestrator.

Runs both analyze_post_soak.py and extract_post_soak_snapshot.py in sequence,
then exits with appropriate code based on verdict.

Usage:
    python -m tools.soak.soak_gate [--path PATH] [--prometheus] [--compare BASELINE]

Exit codes:
    0 = PASS or WARN
    1 = FAIL or error
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Tuple


def run_analyzer(path: Path) -> Tuple[bool, str]:
    """
    Run analyze_post_soak.py.
    
    Returns:
        (success: bool, error_msg: str)
    """
    print("[soak_gate] Running analyze_post_soak.py...")
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tools.soak.analyze_post_soak", "--path", str(path)],
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout
        )
        
        print(result.stdout, end="")
        
        if result.returncode not in (0, 1):  # Allow WARN (0) and FAIL (1)
            return False, f"Analyzer failed with exit code {result.returncode}"
        
        return True, ""
        
    except subprocess.TimeoutExpired:
        return False, "Analyzer timeout (>5 minutes)"
    except Exception as e:
        return False, f"Analyzer error: {e}"


def run_extractor(
    path: Path,
    prometheus: bool = False,
    compare: str = None
) -> Tuple[bool, dict, str]:
    """
    Run extract_post_soak_snapshot.py.
    
    Returns:
        (success: bool, snapshot: dict, error_msg: str)
    """
    print("\n[soak_gate] Running extract_post_soak_snapshot.py...")
    
    cmd = [sys.executable, "-m", "tools.soak.extract_post_soak_snapshot", "--path", str(path)]
    
    if prometheus:
        cmd.append("--prometheus")
    
    if compare:
        cmd.extend(["--compare", compare])
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60  # 1 minute timeout
        )
        
        # Print stderr (logs)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        
        if result.returncode != 0:
            return False, {}, f"Extractor failed with exit code {result.returncode}"
        
        # Parse JSON from stdout
        try:
            snapshot = json.loads(result.stdout.strip())
            return True, snapshot, ""
        except json.JSONDecodeError as e:
            return False, {}, f"Failed to parse snapshot JSON: {e}"
        
    except subprocess.TimeoutExpired:
        return False, {}, "Extractor timeout (>1 minute)"
    except Exception as e:
        return False, {}, f"Extractor error: {e}"


def run_delta_verifier(path: Path, strict: bool = False) -> Tuple[bool, dict, str]:
    """
    Run verify_deltas_applied.py with --json output.
    
    Returns:
        (success: bool, metrics: dict, error_msg: str)
    """
    print("\n[soak_gate] Running verify_deltas_applied.py...")
    
    cmd = [
        sys.executable, "-m", "tools.soak.verify_deltas_applied",
        "--path", str(path),
        "--json"
    ]
    
    if strict:
        cmd.append("--strict")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60  # 1 minute timeout
        )
        
        # Print stderr (logs)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        
        # Parse JSON from stdout (even if exit code is non-zero)
        try:
            metrics = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            metrics = {}
        
        if result.returncode != 0:
            return False, metrics, f"Delta verifier failed (exit code {result.returncode})"
        
        return True, metrics, ""
        
    except subprocess.TimeoutExpired:
        return False, {}, "Delta verifier timeout (>1 minute)"
    except Exception as e:
        return False, {}, f"Delta verifier error: {e}"


def export_delta_metrics(path: Path, metrics: dict):
    """
    Export delta-quality metrics to POST_SOAK_METRICS.prom.
    
    Appends delta metrics to existing Prometheus file if it exists.
    """
    print("\n[soak_gate] Exporting delta metrics to Prometheus format...")
    
    metrics_path = path / "POST_SOAK_METRICS.prom"
    
    # Prepare metrics lines
    lines = [
        "",
        "# Delta application quality",
        f"soak_delta_full_apply_ratio {metrics.get('full_apply_ratio', 0):.3f}",
        f"soak_delta_full_apply_count {metrics.get('full_apply_count', 0)}",
        f"soak_delta_partial_ok_count {metrics.get('partial_ok_count', 0)}",
        f"soak_delta_fail_count {metrics.get('fail_count', 0)}",
        f"soak_delta_signature_stuck_count {metrics.get('signature_stuck_count', 0)}",
        f"soak_delta_proposed_count {metrics.get('proposed_count', 0)}",
        "",
    ]
    
    # Append to file
    with open(metrics_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    print(f"[OK] Delta metrics written to: {metrics_path}")


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Unified Soak Gate Orchestrator"
    )
    parser.add_argument(
        "--path",
        type=str,
        default="artifacts/soak/latest",
        help="Path to soak/latest directory (default: artifacts/soak/latest)",
    )
    parser.add_argument(
        "--prometheus",
        action="store_true",
        help="Export Prometheus metrics via extractor",
    )
    parser.add_argument(
        "--compare",
        type=str,
        metavar="BASELINE",
        help="Compare with baseline snapshot",
    )
    parser.add_argument(
        "--skip-analyzer",
        action="store_true",
        help="Skip analyze_post_soak.py (only run extractor)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Use strict delta verification (>=95%% full apply ratio)",
    )
    parser.add_argument(
        "--skip-delta-verify",
        action="store_true",
        help="Skip delta verification (not recommended)",
    )
    
    args = parser.parse_args()
    
    path = Path(args.path).resolve()
    
    if not path.exists():
        print(f"[ERROR] Path does not exist: {path}", file=sys.stderr)
        sys.exit(1)
    
    print("=" * 80)
    print("SOAK GATE ORCHESTRATOR")
    print("=" * 80)
    print(f"Path: {path}")
    print(f"Strict mode: {args.strict}")
    print("=" * 80)
    print()
    
    # Step 1: Run analyzer (unless skipped)
    if not args.skip_analyzer:
        success, error = run_analyzer(path)
        if not success:
            print(f"\n[ERROR] Analyzer failed: {error}", file=sys.stderr)
            sys.exit(1)
        print("[OK] Analyzer completed")
    else:
        print("[SKIP] Analyzer skipped (--skip-analyzer)")
    
    # Step 2: Run extractor
    success, snapshot, error = run_extractor(path, args.prometheus, args.compare)
    if not success:
        print(f"\n[ERROR] Extractor failed: {error}", file=sys.stderr)
        sys.exit(1)
    
    print("[OK] Extractor completed")
    
    # Step 3: Run delta verifier (unless skipped)
    delta_metrics = {}
    if not args.skip_delta_verify:
        success, delta_metrics, error = run_delta_verifier(path, strict=args.strict)
        if not success:
            print(f"\n[ERROR] Delta verifier failed: {error}", file=sys.stderr)
            # Don't exit yet, but record failure
        else:
            print("[OK] Delta verifier completed")
        
        # Export delta metrics to Prometheus if requested
        if args.prometheus and delta_metrics:
            export_delta_metrics(path, delta_metrics)
    else:
        print("[SKIP] Delta verifier skipped (--skip-delta-verify)")
    
    # Step 4: Determine final verdict
    verdict = snapshot.get("verdict", "UNKNOWN")
    freeze_ready = snapshot.get("freeze_ready", False)
    pass_count = snapshot.get("pass_count_last8", 0)
    
    # Delta metrics
    delta_ratio = delta_metrics.get("full_apply_ratio", 0.0)
    delta_stuck = delta_metrics.get("signature_stuck_count", 0)
    
    print()
    print("=" * 80)
    print("FINAL VERDICT")
    print("=" * 80)
    print(f"Verdict:           {verdict}")
    print(f"Freeze Ready:      {freeze_ready}")
    print(f"Pass Count:        {pass_count}/8")
    if delta_metrics:
        print(f"Delta Apply Ratio: {delta_ratio:.1%}")
        print(f"Signature Stuck:   {delta_stuck}")
    print("=" * 80)
    
    # Gate logic (strict)
    failures = []
    
    if verdict == "FAIL":
        failures.append(f"Verdict is FAIL")
    
    if not freeze_ready:
        failures.append("freeze_ready is False")
    
    if delta_metrics and not args.skip_delta_verify:
        # Check delta quality
        threshold = 0.95 if args.strict else 0.90
        if delta_ratio < threshold:
            failures.append(f"Delta apply ratio {delta_ratio:.1%} < {threshold:.0%}")
        
        if delta_stuck > 1:
            failures.append(f"Signature stuck count {delta_stuck} > 1")
    
    # Exit based on failures
    if failures:
        print("\n[FAIL] Soak gate failures:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    elif verdict == "WARN":
        print("\n[WARN] Soak gate: WARN (continuing)")
        sys.exit(0)
    else:
        print("\n[OK] Soak gate: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()


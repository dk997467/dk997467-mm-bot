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
    
    args = parser.parse_args()
    
    path = Path(args.path).resolve()
    
    if not path.exists():
        print(f"[ERROR] Path does not exist: {path}", file=sys.stderr)
        sys.exit(1)
    
    print("=" * 80)
    print("SOAK GATE ORCHESTRATOR")
    print("=" * 80)
    print(f"Path: {path}")
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
    
    # Step 3: Determine final verdict
    verdict = snapshot.get("verdict", "UNKNOWN")
    freeze_ready = snapshot.get("freeze_ready", False)
    pass_count = snapshot.get("pass_count_last8", 0)
    
    print()
    print("=" * 80)
    print("FINAL VERDICT")
    print("=" * 80)
    print(f"Verdict:      {verdict}")
    print(f"Freeze Ready: {freeze_ready}")
    print(f"Pass Count:   {pass_count}/8")
    print("=" * 80)
    
    # Exit based on verdict
    if verdict == "PASS":
        print("\n[OK] Soak gate: PASS")
        sys.exit(0)
    elif verdict == "WARN":
        print("\n[WARN] Soak gate: WARN (continuing)")
        sys.exit(0)
    else:
        print("\n[FAIL] Soak gate: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()


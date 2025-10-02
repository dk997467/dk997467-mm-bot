#!/usr/bin/env python3
"""
Isolated debug script to diagnose tests_whitelist failures in CI.

This script runs ONLY the failing tests_whitelist step with maximum verbosity
to isolate the problem from other full_stack_validate steps.

Usage:
    python tools/ci/debug_whitelist_test.py
    
Expected behavior:
    - Should run tools/ci/run_selected.py
    - Exit with 0 on success, non-zero on failure
    - Print detailed diagnostics to stdout/stderr
"""
import os
import subprocess
import sys
from pathlib import Path

# Setup paths
ROOT_DIR = Path(__file__).resolve().parents[2]
RUN_SELECTED_SCRIPT = ROOT_DIR / "tools" / "ci" / "run_selected.py"

def main():
    print("=" * 80)
    print("DEBUG WHITELIST TEST - Isolated Diagnostic")
    print("=" * 80)
    print(f"[INFO] Root directory: {ROOT_DIR}")
    print(f"[INFO] Working directory: {os.getcwd()}")
    print(f"[INFO] Python executable: {sys.executable}")
    print(f"[INFO] Python version: {sys.version}")
    print(f"[INFO] Script to run: {RUN_SELECTED_SCRIPT}")
    print(f"[INFO] Script exists: {RUN_SELECTED_SCRIPT.exists()}")
    print()
    
    # Print environment variables (filtered)
    print("[INFO] Relevant environment variables:")
    for key in sorted(os.environ.keys()):
        if any(x in key.upper() for x in ['PYTEST', 'PYTHON', 'PATH', 'PWD', 'MM_']):
            value = os.environ[key]
            # Truncate long PATH values
            if len(value) > 200:
                value = value[:200] + '...'
            print(f"  {key}={value}")
    print()
    
    # Check if run_selected.py exists
    if not RUN_SELECTED_SCRIPT.exists():
        print(f"[ERROR] Script not found: {RUN_SELECTED_SCRIPT}", file=sys.stderr)
        return 1
    
    # Build command with maximum verbosity
    cmd = [sys.executable, str(RUN_SELECTED_SCRIPT), "-vv"]
    
    print("=" * 80)
    print(f"[INFO] Running command: {' '.join(cmd)}")
    print("=" * 80)
    print()
    
    # Run with inherit (stream output directly to console)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            text=True,
            # Inherit stdout/stderr for real-time output
            stdout=None,
            stderr=None,
        )
        
        print()
        print("=" * 80)
        print(f"[INFO] Process finished with return code: {result.returncode}")
        print("=" * 80)
        
        return result.returncode
    
    except Exception as e:
        print(f"[ERROR] Failed to run command: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())


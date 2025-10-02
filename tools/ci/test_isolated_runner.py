#!/usr/bin/env python3
"""
Ultra-Isolated Test Runner - Run each test file in separate pytest process

This is the MOST aggressive isolation strategy:
- Each test file runs in its own pytest process
- Memory is completely freed between tests
- Can identify exactly which test file causes OOM

Usage:
    python tools/ci/test_isolated_runner.py --test-file test_selection_unit.txt
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict

ROOT_DIR = Path(__file__).resolve().parents[2]

def load_test_list(test_file: Path) -> List[str]:
    """Load test paths from selection file."""
    if not test_file.exists():
        print(f"ERROR: Test file not found: {test_file}", file=sys.stderr)
        sys.exit(2)
    
    tests = []
    for line in test_file.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tests.append(line)
    
    return tests

def run_isolated_test(test_path: str, test_num: int, total: int) -> Dict:
    """Run single test file in isolated pytest process."""
    print("=" * 80)
    print(f"[{test_num}/{total}] Running: {test_path}")
    print("=" * 80)
    
    # Build command - each test runs in completely isolated process
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",          # Quiet mode
        "--tb=short",  # Short traceback
        test_path,
    ]
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=120,  # 2 min per test file
        )
        
        duration = time.time() - start_time
        
        status = "✅ PASS" if result.returncode == 0 else f"❌ FAIL (exit {result.returncode})"
        print(f"[{test_num}/{total}] {status} - {duration:.1f}s - {test_path}")
        
        # Print output if failed
        if result.returncode != 0:
            print()
            print("--- STDOUT ---")
            print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
            print("--- STDERR ---")
            print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
            print()
        
        return {
            "test": test_path,
            "exit_code": result.returncode,
            "passed": result.returncode == 0,
            "duration": duration,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    
    except subprocess.TimeoutExpired:
        print(f"[{test_num}/{total}] ⏱️ TIMEOUT (>2min) - {test_path}", file=sys.stderr)
        return {
            "test": test_path,
            "exit_code": -1,
            "passed": False,
            "duration": 120.0,
            "error": "TIMEOUT",
        }
    
    except Exception as e:
        print(f"[{test_num}/{total}] ❌ ERROR: {e} - {test_path}", file=sys.stderr)
        return {
            "test": test_path,
            "exit_code": -1,
            "passed": False,
            "duration": 0.0,
            "error": str(e),
        }

def main():
    parser = argparse.ArgumentParser(description="Run each test in isolated process")
    parser.add_argument(
        "--test-file",
        type=str,
        required=True,
        help="Test selection file (e.g., test_selection_unit.txt)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first failing test",
    )
    
    args = parser.parse_args()
    
    # Load tests
    test_file = ROOT_DIR / "tools" / "ci" / args.test_file
    all_tests = load_test_list(test_file)
    
    print("=" * 80)
    print("ULTRA-ISOLATED TEST RUNNER")
    print("=" * 80)
    print(f"Test file: {test_file}")
    print(f"Total tests: {len(all_tests)}")
    print(f"Strategy: Each test in separate pytest process")
    print(f"Fail fast: {args.fail_fast}")
    print("=" * 80)
    print()
    
    # Run tests one by one
    results = []
    failed_tests = []
    
    for i, test_path in enumerate(all_tests, 1):
        result = run_isolated_test(test_path, i, len(all_tests))
        results.append(result)
        
        if not result["passed"]:
            failed_tests.append(test_path)
            
            if args.fail_fast:
                print()
                print("=" * 80)
                print("⚠️ FAIL-FAST: Stopping on first failure")
                print("=" * 80)
                break
    
    # Summary
    print()
    print("=" * 80)
    print("ISOLATED RUNNER SUMMARY")
    print("=" * 80)
    print(f"Total tests: {len(all_tests)}")
    print(f"Passed: {len([r for r in results if r['passed']])}")
    print(f"Failed: {len([r for r in results if not r['passed']])}")
    
    total_duration = sum(r["duration"] for r in results)
    print(f"Total duration: {total_duration:.1f}s ({total_duration/60:.1f} min)")
    print()
    
    if failed_tests:
        print("❌ FAILED TESTS:")
        for test in failed_tests:
            result = next(r for r in results if r["test"] == test)
            exit_code = result.get("exit_code", -1)
            error = result.get("error", "")
            print(f"  - {test} (exit {exit_code}) {error}")
        
        # Check for exit 143 specifically
        exit_143_tests = [
            r["test"] for r in results 
            if r.get("exit_code") == 143
        ]
        
        if exit_143_tests:
            print()
            print("🚨 EXIT 143 (OOM) DETECTED IN:")
            for test in exit_143_tests:
                print(f"  - {test}")
            print()
            print("These tests are consuming too much memory!")
        
        sys.exit(1)
    else:
        print("✅ ALL TESTS PASSED")
        sys.exit(0)

if __name__ == "__main__":
    main()


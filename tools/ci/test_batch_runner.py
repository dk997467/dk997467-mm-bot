#!/usr/bin/env python3
"""
Batch Test Runner - Run tests in small isolated batches to identify memory hogs

This script runs pytest tests in small batches (configurable size) to:
1. Isolate which batch causes OOM
2. Limit memory accumulation per batch
3. Provide detailed logging per batch

Usage:
    python tools/ci/test_batch_runner.py --batch-size 5 --test-file test_selection_unit.txt
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List

# Setup
ROOT_DIR = Path(__file__).resolve().parents[2]

def load_test_list(test_file: Path) -> List[str]:
    """Load test paths from selection file, filtering comments and empty lines."""
    if not test_file.exists():
        print(f"ERROR: Test file not found: {test_file}", file=sys.stderr)
        sys.exit(2)
    
    tests = []
    for line in test_file.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tests.append(line)
    
    return tests

def run_batch(batch_id: int, tests: List[str], verbose: bool = False) -> dict:
    """Run a batch of tests and return results."""
    print("=" * 80)
    print(f"BATCH {batch_id}: Running {len(tests)} tests")
    print("=" * 80)
    
    for i, test in enumerate(tests, 1):
        print(f"  [{i}/{len(tests)}] {test}")
    print()
    
    # Build pytest command
    cmd = [sys.executable, "-m", "pytest", "-q"]
    
    if verbose:
        cmd.append("-vv")
    
    # Add test paths
    cmd.extend(tests)
    
    # Run
    print(f"[BATCH {batch_id}] Command: {' '.join(cmd)}")
    print(f"[BATCH {batch_id}] Starting at: {__import__('datetime').datetime.now().isoformat()}")
    print()
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=300,  # 5 min per batch
        )
        
        print(f"[BATCH {batch_id}] Exit code: {result.returncode}")
        print(f"[BATCH {batch_id}] Finished at: {__import__('datetime').datetime.now().isoformat()}")
        
        # Print output
        if result.stdout:
            print(f"\n[BATCH {batch_id}] STDOUT:")
            print(result.stdout)
        
        if result.stderr:
            print(f"\n[BATCH {batch_id}] STDERR:")
            print(result.stderr)
        
        return {
            "batch_id": batch_id,
            "tests": tests,
            "exit_code": result.returncode,
            "passed": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    
    except subprocess.TimeoutExpired:
        print(f"\n[BATCH {batch_id}] ⏱️ TIMEOUT after 5 minutes", file=sys.stderr)
        return {
            "batch_id": batch_id,
            "tests": tests,
            "exit_code": -1,
            "passed": False,
            "error": "TIMEOUT",
        }
    
    except Exception as e:
        print(f"\n[BATCH {batch_id}] ❌ ERROR: {e}", file=sys.stderr)
        return {
            "batch_id": batch_id,
            "tests": tests,
            "exit_code": -1,
            "passed": False,
            "error": str(e),
        }

def main():
    parser = argparse.ArgumentParser(description="Run pytest tests in batches")
    parser.add_argument(
        "--test-file",
        type=str,
        required=True,
        help="Test selection file (e.g., test_selection_unit.txt)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Number of tests per batch (default: 5)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose pytest output (-vv)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first failing batch",
    )
    
    args = parser.parse_args()
    
    # Load tests
    test_file = ROOT_DIR / "tools" / "ci" / args.test_file
    all_tests = load_test_list(test_file)
    
    print("=" * 80)
    print("BATCH TEST RUNNER")
    print("=" * 80)
    print(f"Test file: {test_file}")
    print(f"Total tests: {len(all_tests)}")
    print(f"Batch size: {args.batch_size}")
    print(f"Fail fast: {args.fail_fast}")
    print("=" * 80)
    print()
    
    # Split into batches
    batches = []
    for i in range(0, len(all_tests), args.batch_size):
        batch = all_tests[i:i + args.batch_size]
        batches.append(batch)
    
    print(f"Total batches: {len(batches)}")
    print()
    
    # Run batches
    results = []
    failed_batches = []
    
    for batch_id, batch_tests in enumerate(batches, 1):
        result = run_batch(batch_id, batch_tests, args.verbose)
        results.append(result)
        
        if not result["passed"]:
            failed_batches.append(batch_id)
            print()
            print("=" * 80)
            print(f"⚠️ BATCH {batch_id} FAILED")
            print("=" * 80)
            print(f"Tests in failing batch:")
            for test in batch_tests:
                print(f"  - {test}")
            print()
            
            if args.fail_fast:
                print("[FAIL-FAST] Stopping on first failure")
                break
        
        print()
    
    # Summary
    print("=" * 80)
    print("BATCH RUNNER SUMMARY")
    print("=" * 80)
    print(f"Total batches: {len(batches)}")
    print(f"Passed: {len([r for r in results if r['passed']])}")
    print(f"Failed: {len([r for r in results if not r['passed']])}")
    print()
    
    if failed_batches:
        print(f"Failed batch IDs: {failed_batches}")
        print()
        print("Failed batches details:")
        for batch_id in failed_batches:
            result = results[batch_id - 1]
            print(f"\nBatch {batch_id}:")
            for test in result["tests"]:
                print(f"  - {test}")
        
        sys.exit(1)
    else:
        print("✅ ALL BATCHES PASSED")
        sys.exit(0)

if __name__ == "__main__":
    main()


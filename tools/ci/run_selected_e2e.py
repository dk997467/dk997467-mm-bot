#!/usr/bin/env python3
"""
Run E2E tests from test_selection_e2e.txt

E2E tests are:
- Slower (5-8 minutes)
- Higher memory usage
- Heavy fixtures and test data
- Run sequentially to avoid OOM
"""
import os, sys, subprocess, pathlib

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD","1")
os.environ.setdefault("TZ","UTC")
os.environ.setdefault("LC_ALL","C")
os.environ.setdefault("LANG","C")
os.environ.setdefault("CI_QUARANTINE","1")

root = pathlib.Path(__file__).resolve().parents[2]
sel = root / "tools" / "ci" / "test_selection_e2e.txt"
if not sel.exists():
    print("ERROR: test_selection_e2e.txt not found", file=sys.stderr)
    sys.exit(2)

paths = [p.strip() for p in sel.read_text(encoding="ascii").splitlines() 
         if p.strip() and not p.strip().startswith("#")]

# E2E tests: Run ONE AT A TIME with aggressive isolation to prevent zombie processes
# Many E2E tests spawn multiple subprocesses (subprocess.run, Popen)
# Running them together causes process accumulation and CPU overload
# Strategy: Run each test file separately with timeout and process cleanup

import time
total_passed = 0
total_failed = 0
total_skipped = 0
failed_tests = []

print(f"Running {len(paths)} E2E test files sequentially...")
for i, test_path in enumerate(paths, 1):
    print(f"\n[{i}/{len(paths)}] {test_path}", flush=True)
    
    # Run single test file with 5 minute timeout
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=line", test_path]
    try:
        r = subprocess.run(cmd, check=False, timeout=300, capture_output=True, text=True)
        
        # Parse pytest output for stats
        output = r.stdout + r.stderr
        if "passed" in output:
            print(f"    ✓ Test completed", flush=True)
        if r.returncode != 0:
            failed_tests.append(test_path)
            print(f"    ✗ Test failed (exit {r.returncode})", flush=True)
            # Show last few lines of output for debugging
            lines = output.strip().split('\n')[-5:]
            for line in lines:
                print(f"      {line}", flush=True)
        
        # Brief pause to allow OS to cleanup processes
        time.sleep(0.5)
        
    except subprocess.TimeoutExpired:
        print(f"    ⏱ Test exceeded 5 minute timeout", flush=True)
        failed_tests.append(test_path)
        
    except KeyboardInterrupt:
        print("\n\n⚠ Tests interrupted by user", file=sys.stderr)
        sys.exit(130)

# Final summary
print("\n" + "="*60)
print("E2E TESTS SUMMARY")
print("="*60)
print(f"Total files: {len(paths)}")
print(f"Failed: {len(failed_tests)}")
if failed_tests:
    print("\nFailed tests:")
    for t in failed_tests:
        print(f"  - {t}")
    sys.exit(1)
else:
    print("\n✅ All E2E tests passed!")
    sys.exit(0)


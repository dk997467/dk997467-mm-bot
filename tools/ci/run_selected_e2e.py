#!/usr/bin/env python3
"""
Run E2E tests from test_selection_e2e.txt

E2E tests are:
- Slower (5-8 minutes)
- Higher memory usage
- Heavy fixtures and test data
- Run sequentially to avoid OOM
"""
import os, sys, subprocess, pathlib, signal

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

def kill_all_python_children():
    """Kill all Python child processes to prevent zombie accumulation."""
    try:
        import psutil
        current = psutil.Process()
        children = current.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except:
                pass
        # Wait for processes to die
        psutil.wait_procs(children, timeout=3)
    except ImportError:
        # Fallback: kill process group (Unix-like systems)
        if hasattr(signal, 'SIGTERM'):
            try:
                os.killpg(os.getpgid(os.getpid()), signal.SIGTERM)
            except:
                pass

print(f"Running {len(paths)} E2E test files sequentially...")
for i, test_path in enumerate(paths, 1):
    print(f"\n[{i}/{len(paths)}] {test_path}", flush=True)
    
    # Run single test file with 5 minute timeout
    # Use Popen for better process control
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=line", test_path]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = proc.communicate(timeout=300)
            r_code = proc.returncode
        except subprocess.TimeoutExpired:
            # Kill the process and all its children
            proc.kill()
            proc.wait()
            print(f"    [TIMEOUT] Test exceeded 5 minute timeout", flush=True)
            failed_tests.append(test_path)
            kill_all_python_children()
            time.sleep(1)
            continue
        
        # Parse pytest output for stats
        output = stdout + stderr
        if "passed" in output:
            print(f"    [OK] Test completed", flush=True)
        if r_code != 0:
            failed_tests.append(test_path)
            print(f"    [FAIL] Test failed (exit {r_code})", flush=True)
            # Show last few lines of output for debugging
            lines = output.strip().split('\n')[-5:]
            for line in lines:
                print(f"      {line}", flush=True)
        
        # Aggressive cleanup: kill any remaining child processes
        kill_all_python_children()
        
        # Longer pause to allow OS to cleanup processes
        time.sleep(2)
        
    except KeyboardInterrupt:
        print("\n\n[INTERRUPT] Tests interrupted by user", file=sys.stderr)
        kill_all_python_children()
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
    print("\n[SUCCESS] All E2E tests passed!")
    sys.exit(0)


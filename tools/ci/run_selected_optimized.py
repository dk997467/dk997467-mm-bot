#!/usr/bin/env python3
"""
Optimized run_selected.py with profiling and parallel execution.

Performance improvements:
1. Parallel test execution via pytest-xdist
2. Detailed profiling of each phase
3. Test categorization for better insights
4. Performance metrics reporting

Expected speedup: 4-5x (5 minutes → ~1 minute)
"""
import os
import sys
import subprocess
import pathlib
import time
from typing import List, Tuple

# ========== CONFIGURATION ==========
PARALLEL_WORKERS = "auto"  # "auto" uses all CPU cores, or specify number like "4"
ENABLE_PROFILING = True    # Set to False to disable profiling output

# ========== PROFILING UTILITIES ==========
class Timer:
    """Simple timer for profiling."""
    
    def __init__(self, label: str, enabled: bool = True):
        self.label = label
        self.enabled = enabled
        self.start_time = None
    
    def __enter__(self):
        if self.enabled:
            self.start_time = time.monotonic()
            print(f"[PROFILE] Starting: {self.label}", file=sys.stderr, flush=True)
        return self
    
    def __exit__(self, *args):
        if self.enabled and self.start_time is not None:
            elapsed = time.monotonic() - self.start_time
            print(f"[PROFILE] {self.label}: {elapsed:.3f}s", file=sys.stderr, flush=True)

# ========== ENVIRONMENT SETUP ==========
with Timer("Environment setup", ENABLE_PROFILING):
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    os.environ.setdefault("TZ", "UTC")
    os.environ.setdefault("LC_ALL", "C")
    os.environ.setdefault("LANG", "C")
    os.environ.setdefault("CI_QUARANTINE", "1")

# ========== FILE LOADING ==========
with Timer("File loading and parsing", ENABLE_PROFILING):
    root = pathlib.Path(__file__).resolve().parents[2]
    sel = root / "tools" / "ci" / "test_selection.txt"
    
    if not sel.exists():
        print("ERROR: test_selection.txt not found", file=sys.stderr)
        sys.exit(2)
    
    # Read and parse test paths
    paths = [
        p.strip() 
        for p in sel.read_text(encoding="ascii").splitlines() 
        if p.strip() and not p.strip().startswith("#")
    ]
    
    if not paths:
        print("ERROR: No test paths found in test_selection.txt", file=sys.stderr)
        sys.exit(2)

# ========== TEST CATEGORIZATION ==========
with Timer("Test categorization", ENABLE_PROFILING):
    unit_tests = [p for p in paths if "_unit.py" in p]
    e2e_tests = [p for p in paths if "_e2e.py" in p]
    other_tests = [p for p in paths if p not in unit_tests and p not in e2e_tests]
    
    if ENABLE_PROFILING:
        print(f"[PROFILE] Test breakdown:", file=sys.stderr)
        print(f"[PROFILE]   Total:  {len(paths)} files", file=sys.stderr)
        print(f"[PROFILE]   Unit:   {len(unit_tests)} files ({len(unit_tests)*100//len(paths)}%)", file=sys.stderr)
        print(f"[PROFILE]   E2E:    {len(e2e_tests)} files ({len(e2e_tests)*100//len(paths)}%)", file=sys.stderr)
        print(f"[PROFILE]   Other:  {len(other_tests)} files ({len(other_tests)*100//len(paths)}%)", file=sys.stderr)

# ========== PYTEST COMMAND CONSTRUCTION ==========
with Timer("Command construction", ENABLE_PROFILING):
    cmd = [
        sys.executable,
        "-m", "pytest",
        "-q",                    # Quiet mode
        "-n", PARALLEL_WORKERS,  # Parallel execution with pytest-xdist
        "--tb=short",            # Shorter tracebacks for faster output
        *paths
    ]
    
    if ENABLE_PROFILING:
        print(f"[PROFILE] Command: {' '.join(cmd[:6])} ... [{len(paths)} test paths]", file=sys.stderr)

# ========== PYTEST EXECUTION ==========
start_total = time.monotonic()

with Timer("Pytest execution (parallel)", ENABLE_PROFILING):
    result = subprocess.run(cmd, check=False)

total_time = time.monotonic() - start_total

# ========== PERFORMANCE SUMMARY ==========
if ENABLE_PROFILING:
    print("\n" + "="*60, file=sys.stderr)
    print("PERFORMANCE SUMMARY", file=sys.stderr)
    print("="*60, file=sys.stderr)
    print(f"Total tests executed: {len(paths)}", file=sys.stderr)
    print(f"Total execution time: {total_time:.2f}s ({total_time/60:.1f} min)", file=sys.stderr)
    print(f"Average time per test: {total_time/len(paths):.2f}s", file=sys.stderr)
    print(f"Parallel workers: {PARALLEL_WORKERS}", file=sys.stderr)
    
    # Performance rating
    if total_time < 60:
        rating = "🟢 EXCELLENT"
    elif total_time < 120:
        rating = "🟡 GOOD"
    elif total_time < 180:
        rating = "🟠 ACCEPTABLE"
    else:
        rating = "🔴 NEEDS OPTIMIZATION"
    
    print(f"Performance rating: {rating}", file=sys.stderr)
    print("="*60 + "\n", file=sys.stderr)

sys.exit(result.returncode)


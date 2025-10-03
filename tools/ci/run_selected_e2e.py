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

# E2E tests: Run sequentially (-n 0) to prevent memory accumulation and OOM
# Note: With PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, must explicitly load xdist via -p
# Using -n 0 (no parallelism) to keep memory usage low
# Add timeout to prevent zombie processes (30 minutes max for all E2E tests)
cmd = [sys.executable, "-m", "pytest", "-q", *paths]
try:
    r = subprocess.run(cmd, check=False, timeout=1800)  # 30 min timeout
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    print("ERROR: E2E tests exceeded 30 minute timeout", file=sys.stderr)
    sys.exit(124)  # Standard timeout exit code


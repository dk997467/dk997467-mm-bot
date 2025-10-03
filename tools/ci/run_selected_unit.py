#!/usr/bin/env python3
"""
Run unit tests from test_selection_unit.txt

Unit tests are:
- Fast (2-3 minutes)
- Low memory usage
- No heavy fixtures
- Good for quick feedback
"""
import os, sys, subprocess, pathlib

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD","1")
os.environ.setdefault("TZ","UTC")
os.environ.setdefault("LC_ALL","C")
os.environ.setdefault("LANG","C")
os.environ.setdefault("CI_QUARANTINE","1")

root = pathlib.Path(__file__).resolve().parents[2]
sel = root / "tools" / "ci" / "test_selection_unit.txt"
if not sel.exists():
    print("ERROR: test_selection_unit.txt not found", file=sys.stderr)
    sys.exit(2)

paths = [p.strip() for p in sel.read_text(encoding="ascii").splitlines() 
         if p.strip() and not p.strip().startswith("#")]

# Unit tests: Run sequentially to prevent zombie processes from subprocess-heavy tests
# Many tests spawn subprocesses (daily_check, postmortem, etc.)
# Parallel execution can cause CPU overload and zombie process accumulation
# Timeout: 15 minutes should be enough for all unit tests sequentially
cmd = [sys.executable, "-m", "pytest", "-q", *paths]
try:
    r = subprocess.run(cmd, check=False, timeout=900)  # 15 min timeout
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    print("ERROR: Unit tests exceeded 15 minute timeout", file=sys.stderr)
    sys.exit(124)  # Standard timeout exit code


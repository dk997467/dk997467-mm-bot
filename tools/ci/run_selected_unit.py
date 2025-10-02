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

# Unit tests: Use -n 2 for speed (low memory usage)
# Note: With PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, must explicitly load xdist via -p
cmd = [sys.executable, "-m", "pytest", "-q", "-p", "xdist", "-n", "2", *paths]
r = subprocess.run(cmd, check=False)
sys.exit(r.returncode)


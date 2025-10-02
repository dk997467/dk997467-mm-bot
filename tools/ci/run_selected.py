#!/usr/bin/env python3
import os, sys, subprocess, pathlib

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD","1")
os.environ.setdefault("TZ","UTC")
os.environ.setdefault("LC_ALL","C")
os.environ.setdefault("LANG","C")
os.environ.setdefault("CI_QUARANTINE","1")  # в CI пропускаем quarantined

root = pathlib.Path(__file__).resolve().parents[2]
sel = root / "tools" / "ci" / "test_selection.txt"
if not sel.exists():
    print("ERROR: test_selection.txt not found", file=sys.stderr)
    sys.exit(2)
paths = [p.strip() for p in sel.read_text(encoding="ascii").splitlines() if p.strip() and not p.strip().startswith("#")]
# Enable parallel execution with limited workers to prevent OOM
# Requires: pytest-xdist (see requirements.txt)
# Note: With PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, we must explicitly load xdist via -p
# Changed from "-n auto" to "-n 2" to avoid SIGTERM (exit code 143) due to memory exhaustion
cmd = [sys.executable, "-m", "pytest", "-q", "-p", "xdist", "-n", "2", *paths]
r = subprocess.run(cmd, check=False)
sys.exit(r.returncode)



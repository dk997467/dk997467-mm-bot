#!/usr/bin/env python3
import os, sys, subprocess

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
os.environ.setdefault("TZ", "UTC")
os.environ.setdefault("LC_ALL", "C")
os.environ.setdefault("LANG", "C")

try:
    subprocess.run([sys.executable, "tools/ci/env_sanity.py"], check=False)
except Exception as e:
    print(f"[run_tests] WARN: env_sanity failed to run: {e}", file=sys.stderr)

# tip: use tools/ci/run_selected.py for step-focused CI runs
cmd = [sys.executable, "-m", "pytest", "-q", *sys.argv[1:]]
try:
    r = subprocess.run(cmd, check=False)
    raise SystemExit(r.returncode)
except KeyboardInterrupt:
    raise SystemExit(130)
except Exception as e:
    print(f"[run_tests] ERROR: {e}", file=sys.stderr)
    raise SystemExit(2)



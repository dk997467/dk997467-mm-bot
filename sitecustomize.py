import os, locale, time, sys
from pathlib import Path

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
os.environ.setdefault("LC_ALL", "C")
os.environ.setdefault("LANG", "C")
os.environ.setdefault("TZ", "UTC")
try:
    time.tzset()
except Exception:
    pass
try:
    locale.setlocale(locale.LC_ALL, "C")
except Exception:
    pass

# Ensure project local paths are importable regardless of external tooling
try:
    repo_root = Path(__file__).resolve().parent
    for rel in ("src", "cli"):
        p = str((repo_root / rel).resolve())
        if p not in sys.path and os.path.isdir(p):
            sys.path.insert(0, p)
except Exception:
    pass



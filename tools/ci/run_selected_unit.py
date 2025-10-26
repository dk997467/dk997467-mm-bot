#!/usr/bin/env python3
"""
Run unit tests from test_selection_unit.txt

Unit tests are:
- Fast (2-3 minutes)
- Low memory usage
- No heavy fixtures
- Good for quick feedback
"""

# --- BEGIN: robust repo root bootstrap ---
import os, sys, importlib, traceback
from pathlib import Path

# Определяем корень репо независимо от точки запуска
# tools/ci/run_selected_unit.py -> parents[2] == repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]

# Сменим рабочую директорию, чтобы pytest видел tests/ и tools/
os.chdir(REPO_ROOT)

# Гарантируем, что корень в sys.path и PYTHONPATH
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ["PYTHONPATH"] = str(REPO_ROOT)

print("[unit-runner] cwd =", os.getcwd())
print("[unit-runner] repo_root =", REPO_ROOT)
print("[unit-runner] has tools/soak? =", (REPO_ROOT / "tools" / "soak").exists())
print("[unit-runner] sys.path[0] =", sys.path[0])

# Диагностика: покажем, какие файлы реально есть в git (иногда ветка/чекаут не тот)
try:
    from subprocess import run, PIPE
    out = run(["git", "ls-files", "tools/soak"], check=False, stdout=PIPE, text=True)
    print("[unit-runner] git ls-files tools/soak:\n", out.stdout or "<empty>")
except Exception as e:
    print("[unit-runner] git ls-files failed:", e)

# Жёсткая пред-проверка импортов (чтобы упасть раньше и с понятной диагностикой)
critical_mods = [
    "tools.soak.drift_guard",
    "tools.soak.regression_guard",
    "tools.soak.anomaly_radar",
]
for m in critical_mods:
    try:
        importlib.import_module(m)
        print(f"[unit-runner] OK import {m}")
    except Exception as e:
        print(f"[unit-runner] FAIL import {m}: {e}")
        traceback.print_exc()
        # Завершаем до pytest с кодом 2, чтобы увидеть понятную ошибку
        sys.exit(2)
# --- END: robust repo root bootstrap ---

import subprocess, pathlib

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD","1")
os.environ.setdefault("TZ","UTC")
os.environ.setdefault("LC_ALL","C")
os.environ.setdefault("LANG","C")
os.environ.setdefault("CI_QUARANTINE","1")

# REPO_ROOT already defined in bootstrap above
sel = REPO_ROOT / "tools" / "ci" / "test_selection_unit.txt"
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
    # CRITICAL: Pass environment to subprocess so PYTHONPATH is visible to pytest
    r = subprocess.run(cmd, check=False, timeout=900, env=os.environ)  # 15 min timeout
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    print("ERROR: Unit tests exceeded 15 minute timeout", file=sys.stderr)
    sys.exit(124)  # Standard timeout exit code


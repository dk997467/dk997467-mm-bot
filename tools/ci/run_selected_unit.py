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

# ЖЁСТКО: корень всегда на позиции 0
repo_str = str(REPO_ROOT)
if sys.path[:1] != [repo_str]:
    sys.path[:] = [repo_str] + [p for p in sys.path if p != repo_str]

# Продублируем в окружение (для любых подпроцессов pytest)
prev = os.environ.get("PYTHONPATH", "")
os.environ["PYTHONPATH"] = repo_str if not prev else (repo_str + os.pathsep + prev)

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
import tools
print("[unit-runner] tools.__file__ =", Path(tools.__file__).resolve())
print("[unit-runner] tools is local? =", Path(tools.__file__).resolve().as_posix().startswith(repo_str))

critical_mods = [
    "tools.soak.drift_guard",
    "tools.soak.regression_guard",
    "tools.soak.anomaly_radar",
]
for m in critical_mods:
    try:
        importlib.import_module(m)
        print(f"[unit-runner] OK pre-import {m}")
    except Exception as e:
        print(f"[unit-runner] FAIL import {m}: {e}")
        traceback.print_exc()
        # Завершаем до pytest с кодом 2, чтобы увидеть понятную ошибку
        sys.exit(2)
# --- END: robust repo root bootstrap ---

import subprocess, pathlib, compileall, shlex

# --- BEGIN: Syntax check ---
print("[unit-runner] Running syntax check on ./tools...")
if not compileall.compile_dir("tools", quiet=1):
    print("[CI] ERROR: Syntax check failed in ./tools", file=sys.stderr)
    print("[CI] Fix syntax errors before running tests", file=sys.stderr)
    sys.exit(3)
print("[unit-runner] OK: Syntax check passed")
# --- END: Syntax check ---

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

# --- BEGIN: Coverage plugin injection ---
def _ensure_pytest_cov_loaded(pytest_args: list) -> list:
    """
    Если переданы флаги --cov*, а автозагрузка плагинов отключена,
    инжектим явную загрузку плагина: -p pytest_cov.
    """
    need_cov = any(a.startswith("--cov") for a in pytest_args)
    autoload_off = os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "") == "1"

    if need_cov and autoload_off:
        # Проверим, что плагин установлен
        try:
            import pytest_cov  # noqa: F401
            print("[unit-runner] OK: pytest-cov detected, will inject -p pytest_cov")
        except ImportError as e:
            print("[CI] ERROR: pytest-cov не доступен, а --cov передан", file=sys.stderr)
            print("[CI] Установите: pip install pytest-cov", file=sys.stderr)
            print(f"[CI] Import error: {e}", file=sys.stderr)
            sys.exit(3)
        
        # Вставим -p pytest_cov в начало, если его ещё нет
        if "-p" not in pytest_args or "pytest_cov" not in " ".join(pytest_args):
            pytest_args = ["-p", "pytest_cov"] + pytest_args
            print("[unit-runner] Injected: -p pytest_cov")
    
    return pytest_args


def _rewrite_cov_targets(args: list[str]) -> list[str]:
    """Заменяем широкое --cov=tools на точечные пакеты с реальными тестами."""
    new_args: list[str] = []
    replaced = False
    for a in args:
        if a.startswith("--cov=tools") and not any(
            a.startswith(f"--cov=tools/{pkg}") 
            for pkg in ["live", "obs", "state", "common", "ci"]
        ):
            # пропускаем это значение
            if not replaced:
                new_args += [
                    "--cov=tools/live",
                    "--cov=tools/obs",
                    "--cov=tools/state",
                    "--cov=tools/common",
                    "--cov=tools/ci",
                ]
                replaced = True
                print("[unit-runner] Rewrote --cov=tools -> точечные пакеты")
        else:
            new_args.append(a)
    return new_args


def _ensure_cov_config(args: list[str]) -> list[str]:
    """Гарантируем, что .coveragerc будет подключён."""
    has_cfg = any(a.startswith("--cov-config") for a in args)
    if not has_cfg and os.path.exists(".coveragerc"):
        args = ["--cov-config=.coveragerc"] + args
        print("[unit-runner] Injected: --cov-config=.coveragerc")
    return args

# Собираем аргументы для pytest
pytest_args_base = ["-q", "-o", "importmode=prepend"]
pytest_args_user = sys.argv[1:]

# Инжектим pytest_cov если нужно
pytest_args_user = _ensure_pytest_cov_loaded(pytest_args_user)

# Перепишем --cov=tools на точечные таргеты
pytest_args_user = _rewrite_cov_targets(pytest_args_user)

# Гарантируем подключение .coveragerc
pytest_args_user = _ensure_cov_config(pytest_args_user)

# Диагностика
print("[unit-runner] PYTEST_DISABLE_PLUGIN_AUTOLOAD =", os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD"))
print("[unit-runner] pytest args:", " ".join(pytest_args_base + paths + pytest_args_user))
# --- END: Coverage plugin injection ---

# Unit tests: Run sequentially to prevent zombie processes from subprocess-heavy tests
# Many tests spawn subprocesses (daily_check, postmortem, etc.)
# Parallel execution can cause CPU overload and zombie process accumulation
# Timeout: 15 minutes should be enough for all unit tests sequentially
# CRITICAL: Use prepend import mode to ensure local 'tools' package is used
# Pass additional CLI arguments (e.g., --cov=tools --cov-fail-under=60)
cmd = [sys.executable, "-m", "pytest", *pytest_args_base, *paths, *pytest_args_user]
try:
    # CRITICAL: Pass environment to subprocess so PYTHONPATH is visible to pytest
    r = subprocess.run(cmd, check=False, timeout=900, env=os.environ)  # 15 min timeout
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    print("ERROR: Unit tests exceeded 15 minute timeout", file=sys.stderr)
    sys.exit(124)  # Standard timeout exit code


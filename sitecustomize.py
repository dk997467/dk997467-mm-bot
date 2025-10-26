# sitecustomize.py — гарантирует, что корень репозитория всегда в sys.path,
# даже когда pytest меняет import-mode или cwd.

import os
import sys
from pathlib import Path

try:
    repo_root = Path(__file__).resolve().parent  # корень репо (где лежит этот файл)
    repo_str = str(repo_root)
    # вставляем корень в начало sys.path, если его там нет/не первый
    if sys.path[:1] != [repo_str]:
        sys.path[:] = [repo_str] + [p for p in sys.path if p != repo_str]

    # дублируем в PYTHONPATH для дочерних процессов (если появятся)
    prev = os.environ.get("PYTHONPATH", "")
    if prev:
        os.environ["PYTHONPATH"] = repo_str + os.pathsep + prev
    else:
        os.environ["PYTHONPATH"] = repo_str

    # Опциональная диагностика (оставь закомментированной, если шумно):
    print("[sitecustomize] ensured repo root in sys.path[0]:", sys.path[0])
except Exception as _e:
    # не мешаем тестам даже если тут что-то пошло не так
    pass

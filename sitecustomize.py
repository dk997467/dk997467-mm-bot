# sitecustomize.py — гарантирует, что корень репозитория всегда в sys.path,
# даже когда pytest меняет import-mode или cwd.
# Также защищает от конфликта с внешним пакетом 'tools' из окружения.

import os
import sys
import importlib
from pathlib import Path

try:
    repo_root = Path(__file__).resolve().parent  # корень репо (где лежит этот файл)
    repo_str = str(repo_root)
    
    # 1) вставляем корень в начало sys.path, если его там нет/не первый
    if sys.path[:1] != [repo_str]:
        sys.path[:] = [repo_str] + [p for p in sys.path if p != repo_str]

    # 2) дублируем в PYTHONPATH для дочерних процессов (если появятся)
    prev = os.environ.get("PYTHONPATH", "")
    if prev:
        os.environ["PYTHONPATH"] = repo_str + os.pathsep + prev
    else:
        os.environ["PYTHONPATH"] = repo_str

    # 3) гарантируем, что пакет "tools" — локальный (не из окружения)
    def _is_local_tools(mod):
        """Проверяет, что модуль tools из нашего репо, а не внешний."""
        f = getattr(mod, "__file__", "") or ""
        try:
            return Path(f).resolve().as_posix().startswith(repo_root.as_posix())
        except Exception:
            return False

    # Если 'tools' уже загружен, но это НЕ наш локальный — выбросить
    if "tools" in sys.modules and not _is_local_tools(sys.modules["tools"]):
        sys.modules.pop("tools", None)
        for k in list(sys.modules):
            if k.startswith("tools."):
                sys.modules.pop(k, None)

    # Импортируем локальный tools (если ещё не загружен)
    import tools  # noqa: E402

    # Двойная проверка: если всё ещё не локальный — принудительно перезагрузить
    if not _is_local_tools(tools):
        sys.modules.pop("tools", None)
        for k in list(sys.modules):
            if k.startswith("tools."):
                sys.modules.pop(k, None)
        importlib.invalidate_caches()
        import tools  # noqa: E402

    # Диагностика (можно закомментировать, если шумно)
    print("[sitecustomize] sys.path[0] =", sys.path[0])
    print("[sitecustomize] tools.__file__ =", Path(tools.__file__).resolve())

except Exception as _e:
    # не мешаем тестам даже если тут что-то пошло не так
    pass

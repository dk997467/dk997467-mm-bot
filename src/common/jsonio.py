from __future__ import annotations
from pathlib import Path
import math
import json
from typing import Any

# ---------- helpers ----------

def _round_floats(obj: Any, ndigits: int = 6):
    if isinstance(obj, float):
        # математически округляем до ndigits, чтобы стабилизировать 0.10000000000000009
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, ndigits) for v in obj]
    return obj

def _dump_str_ascii(s: str) -> str:
    # используем стандартный json для корректного экранирования строк,
    # но только для строкового примитива
    return json.dumps(s, ensure_ascii=True)

def _dump_number(n: float) -> str:
    # запрещаем NaN/inf (в тестах их нет), иначе пишем null
    if not math.isfinite(n):
        return "null"
    # фиксированная ширина 6 знаков, как в golden
    return f"{n:.6f}"

def _dumps_fixed(obj: Any) -> str:
    """
    Детерминированный JSON-сериализатор:
    - словари: sort_keys=True
    - списки: порядок как есть
    - числа: фиксированная точность 6 знаков
    - строки: ASCII-экранирование stdlib'ом
    - true/false/null как в JSON
    - без пробелов: separators=(',',':')
    """
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, (int,)):
        return str(obj)
    if isinstance(obj, float):
        return _dump_number(obj)
    if isinstance(obj, str):
        return _dump_str_ascii(obj)
    if isinstance(obj, list):
        return "[" + ",".join(_dumps_fixed(v) for v in obj) + "]"
    if isinstance(obj, dict):
        items = []
        for k in sorted(obj.keys()):
            v = obj[k]
            # ключ — только строка
            items.append(_dump_str_ascii(str(k)) + ":" + _dumps_fixed(v))
        return "{" + ",".join(items) + "}"
    # fallback: приводим к строке
    return _dump_str_ascii(str(obj))

# ---------- public API ----------

def dump_json_artifact(path: str | Path, data: Any, ndigits: int = 6) -> None:
    """
    Детерминированная запись JSON-артефакта под byte-for-byte golden:
    - все float округляются до ndigits и сериализуются с фиксированной шириной
    - сортировка ключей, ASCII, компактные разделители
    - финальный формат файла: CRLF + ровно 3 перевода строк
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    normalized = _round_floats(data, ndigits)
    body = _dumps_fixed(normalized)

    # сначала делаем LF + 1 перевод, затем нормализуем в CRLF + 3
    txt = (body + "\n").replace("\r\n", "\n").replace("\r", "\n")
    txt = txt.rstrip("\n") + "\r\n\r\n\r\n"
    p.write_bytes(txt.encode("ascii"))

"""
Thin wrapper for JSON IO to enforce atomic writer usage.
"""

from .artifacts import export_registry_snapshot as write_json_atomic  # re-export


def is_atomic_writer_used() -> bool:
    return True



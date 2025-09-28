"""
Backtest loader (stdlib-only).

Provides iter_ticks(path) -> Iterator[dict], reading ASCII JSONL with '\n'.
Validation: at minimum require fields 'ts_ms', 'bid', 'ask'.
Sanitize numeric fields: NaN/Inf -> 0.0.
Errors raise one-line ValueError with prefix 'E_BT_LOADER:'.
"""

from typing import Iterator, Dict, Any
import json
import math


_REQ = ("ts_ms", "bid", "ask")
_NUMERIC_FIELDS = ("bid", "ask", "bid_qty", "ask_qty")


def _finite(x: Any) -> float:
    try:
        xx = float(x)
        if math.isfinite(xx):
            return xx
        return 0.0
    except Exception:
        return 0.0


def _validate_tick(t: Dict[str, Any]) -> None:
    for k in _REQ:
        if k not in t:
            raise ValueError("E_BT_LOADER:missing_field")
    # ts_ms must be int-like
    try:
        _ = int(t.get("ts_ms"))
    except Exception:
        raise ValueError("E_BT_LOADER:bad_ts")


def _sanitize_tick(t: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(t)
    # ints
    try:
        out["ts_ms"] = int(out.get("ts_ms", 0))
    except Exception:
        out["ts_ms"] = 0
    # numerics to float finite
    for k in _NUMERIC_FIELDS:
        if k in out:
            out[k] = _finite(out.get(k))
    # trades to int if present
    if "trades" in out:
        try:
            out["trades"] = int(out.get("trades", 0))
        except Exception:
            out["trades"] = 0
    return out


def iter_ticks(path: str) -> Iterator[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="ascii", newline="\n") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    raise ValueError("E_BT_LOADER:bad_json")
                _validate_tick(obj)
                yield _sanitize_tick(obj)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("E_BT_LOADER:io_error")




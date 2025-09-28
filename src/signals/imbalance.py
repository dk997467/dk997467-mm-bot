from typing import Any


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


def ob_imbalance(bid_qty: float, ask_qty: float) -> float:
    try:
        import math
        b_raw = float(bid_qty)
        a_raw = float(ask_qty)
        if not (math.isfinite(b_raw) and math.isfinite(a_raw)):
            return 0.0
    except Exception:
        return 0.0
    b = max(0.0, b_raw)
    a = max(0.0, a_raw)
    tot = b + a
    if tot <= 0.0:
        return 0.0
    x = (b - a) / tot
    if x < -1.0:
        return -1.0
    if x > 1.0:
        return 1.0
    return float(x)



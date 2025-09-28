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


def microprice(bid: float, ask: float, bq: float, aq: float) -> float:
    b = _finite(bid)
    a = _finite(ask)
    qb = max(0.0, _finite(bq))
    qa = max(0.0, _finite(aq))
    den = qb + qa
    if den <= 0.0:
        # fallback mid
        return (b + a) / 2.0
    num = a * qb + b * qa
    return float(num / den)


def micro_tilt(bid: float, ask: float, bq: float, aq: float) -> float:
    b = _finite(bid)
    a = _finite(ask)
    mp = microprice(b, a, bq, aq)
    mid = (b + a) / 2.0
    # linear tilt in [-1,1]: sign(mid - microprice), scaled by relative offset vs half-spread
    half_spread = max(1e-12, (a - b) / 2.0)
    diff = mid - mp
    x = diff / half_spread
    if x < -1.0:
        return -1.0
    if x > 1.0:
        return 1.0
    return float(x)



from typing import List, Tuple


def sigma_band(sigma: float, bands: List[Tuple[float, float, str]]) -> str:
    try:
        x = float(sigma)
    except Exception:
        x = 0.0
    bands = list(bands or [])
    for lo, hi, name in bands:
        try:
            lo_f = float(lo)
            hi_f = float(hi)
        except Exception:
            continue
        if x >= lo_f and x < hi_f:
            return str(name)
    return str(bands[-1][2]) if bands else "unknown"



from typing import Any
import math

from src.common.errors import raise_one_line


def assert_finite(*values: Any, code: str = 'E_CFG_INVARIANT') -> None:
    for v in values:
        try:
            x = float(v)
            if not math.isfinite(x):
                raise_one_line(code, f'non-finite value {v}')
        except Exception:
            raise_one_line(code, f'non-finite value {v}')


def assert_range(x: Any, lo: float, hi: float, code: str = 'E_CFG_RANGE') -> None:
    try:
        xv = float(x)
    except Exception:
        raise_one_line(code, f'not a number: {x}')
    if not (lo <= xv <= hi):
        raise_one_line(code, f'out of range [{lo},{hi}]: {xv}')



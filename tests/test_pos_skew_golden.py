from src.guards.position_skew import PositionSkewGuard


def _eval_abs(pos: float, limit: float) -> float:
    g = PositionSkewGuard(per_symbol_abs_limit=limit, per_color_abs_limit=0.0)
    g.evaluate({'SYMBOL': pos}, {'SYMBOL': 'blue'})
    return g._last_pos_skew_abs.get('SYMBOL', 0.0)


def test_pos_skew_abs_golden():
    # A: 50/100 -> 0.5
    a = _eval_abs(50.0, 100.0)
    assert abs(a - 0.5) <= 1e-12
    # B: 0/100 -> 0.0
    b = _eval_abs(0.0, 100.0)
    assert abs(b - 0.0) <= 1e-12
    # C: -50/100 -> 0.5
    c = _eval_abs(-50.0, 100.0)
    assert abs(c - 0.5) <= 1e-12



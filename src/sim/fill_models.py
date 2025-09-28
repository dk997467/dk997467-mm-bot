from typing import Tuple, Dict, Any


def _finite(x: float) -> float:
    try:
        import math
        xx = float(x)
        if math.isfinite(xx):
            return xx
        return 0.0
    except Exception:
        return 0.0


def fill_conservative(order: Dict[str, Any], book_tick: Dict[str, Any]) -> Tuple[float, float]:
    side = str(order.get("side")).lower()
    price = _finite(order.get("price", 0.0))
    size = _finite(order.get("size", 0.0))
    bid = _finite(book_tick.get("bid", 0.0))
    ask = _finite(book_tick.get("ask", 0.0))
    # Fill only if price crosses opposite
    filled = 0.0
    if size > 0.0:
        if side == "buy" and price >= ask and ask > 0.0:
            filled = size
        elif side == "sell" and price <= bid and bid > 0.0:
            filled = size
    # Simple fee model: maker negative (rebate), taker positive fee
    fees_bps = 5.0 if filled > 0.0 else 0.0
    return float(filled), float(fees_bps)


def fill_queue_aware(order: Dict[str, Any], book_tick: Dict[str, Any], qpos: float, params: Dict[str, Any]) -> Tuple[float, float, float]:
    side = str(order.get("side")).lower()
    price = _finite(order.get("price", 0.0))
    size = _finite(order.get("size", 0.0))
    bid = _finite(book_tick.get("bid", 0.0))
    ask = _finite(book_tick.get("ask", 0.0))
    qpos = max(0.0, min(1.0, _finite(qpos)))
    penalty_bps = _finite(params.get("queue_penalty_bps", 0.0))
    maker_bps = _finite(params.get("maker_bps", -2.0))
    taker_bps = _finite(params.get("taker_bps", 5.0))
    filled = 0.0
    next_qpos = qpos
    if size > 0.0:
        cross = (side == "buy" and ask > 0.0 and price >= ask) or (side == "sell" and bid > 0.0 and price <= bid)
        at_top = (side == "buy" and bid > 0.0 and price == bid) or (side == "sell" and ask > 0.0 and price == ask)
        if cross or at_top:
            frac = max(0.0, min(1.0, 1.0 - qpos))
            filled = size * frac
            next_qpos = 0.0
    if filled > 0.0:
        fees_bps = (taker_bps + penalty_bps) if cross else maker_bps
    else:
        fees_bps = 0.0
    return float(filled), float(next_qpos), float(fees_bps)



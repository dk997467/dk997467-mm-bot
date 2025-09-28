"""
Backtest simulator (stdlib-only, deterministic).

Interface:
    run_sim(ticks, mode: str, params: dict) -> dict
Returns aggregates with deterministic floats rounded at 6 decimals in output.
No IO inside.
"""

from typing import Iterator, Dict, Any, Tuple, List


def _finite(x: float) -> float:
    try:
        import math

        xx = float(x)
        if math.isfinite(xx):
            return xx
        return 0.0
    except Exception:
        return 0.0


def _percentile(values: List[float], p: float) -> float:
    vs = sorted(values)
    if not vs:
        return 0.0
    k = (len(vs) - 1) * p
    f = int(k)
    c = min(f + 1, len(vs) - 1)
    if c == f:
        return float(vs[f])
    w = k - f
    return float(vs[f] * (1 - w) + vs[c] * w)


def _fill_conservative(side: str, price: float, size: float, bid: float, ask: float) -> Tuple[float, float, bool]:
    filled = 0.0
    taker = False
    if size > 0.0 and ask > 0.0 and bid > 0.0:
        if side == "buy" and price >= ask:
            filled = size
            taker = True
        elif side == "sell" and price <= bid:
            filled = size
            taker = True
    fees_bps = 5.0 if filled > 0.0 else 0.0
    return float(filled), float(fees_bps), taker


def _fill_queue_aware(side: str, price: float, size: float, bid: float, ask: float, qpos: float, params: Dict[str, Any]) -> Tuple[float, float, float, bool]:
    qpos = max(0.0, min(1.0, _finite(qpos)))
    penalty_bps = _finite(params.get("queue_penalty_bps", 0.8))
    maker_bps = _finite(params.get("maker_bps", -2.0))
    taker_bps = _finite(params.get("taker_bps", 5.0))
    filled = 0.0
    next_qpos = qpos
    taker = False
    cross = False
    at_top = False
    if size > 0.0 and (ask > 0.0 and bid > 0.0):
        cross = (side == "buy" and price >= ask) or (side == "sell" and price <= bid)
        at_top = (side == "buy" and price == bid) or (side == "sell" and price == ask)
        if cross or at_top:
            frac = max(0.0, min(1.0, 1.0 - qpos))
            filled = size * frac
            next_qpos = 0.0
            taker = bool(cross)
    if filled > 0.0:
        fees_bps = (taker_bps + penalty_bps) if cross else maker_bps
    else:
        fees_bps = 0.0
    return float(filled), float(next_qpos), float(fees_bps), taker


def run_sim(ticks: Iterator[Dict[str, Any]], mode: str, params: Dict[str, Any]) -> Dict[str, Any]:
    # Deterministic state
    fills_total = 0
    taker_count = 0
    fees_bps_acc = 0.0
    turnover_usd = 0.0
    ages: List[float] = []

    # Single passive order placeholder to make deterministic comparisons:
    # Strategy-free: place a mid-price pegged order with small size every tick,
    # but only evaluate fills against book; we don't persist orders, just model a chance per tick.
    qpos_const = float(params.get("initial_qpos_ratio", 0.5))
    size = _finite(params.get("size", 1.0))

    last_bid = 0.0
    last_ask = 0.0
    last_ts = 0

    for t in ticks:
        ts = int(t.get("ts_ms", 0))
        bid = _finite(t.get("bid", 0.0))
        ask = _finite(t.get("ask", 0.0))
        last_bid, last_ask, last_ts = bid, ask, ts

        # We simulate attempting both sides to accumulate stable aggregates
        # Side BUY at bid, side SELL at ask
        # BUY leg
        filled = 0.0
        fees_bps = 0.0
        taker = False
        if mode == "conservative":
            filled, fees_bps, taker = _fill_conservative("buy", bid, size, bid, ask)
        else:
            filled, _qnext, fees_bps, taker = _fill_queue_aware("buy", bid, size, bid, ask, qpos_const, params)
        if filled > 0.0:
            fills_total += 1
            taker_count += 1 if taker else 0
            fees_bps_acc += fees_bps
            turnover_usd += bid * filled
            ages.append(0.0)

        # SELL leg
        if mode == "conservative":
            filled, fees_bps, taker = _fill_conservative("sell", ask, size, bid, ask)
        else:
            filled, _qnext, fees_bps, taker = _fill_queue_aware("sell", ask, size, bid, ask, qpos_const, params)
        if filled > 0.0:
            fills_total += 1
            taker_count += 1 if taker else 0
            fees_bps_acc += fees_bps
            turnover_usd += ask * filled
            ages.append(0.0)

    taker_share_pct = 100.0 * (fills_total and (taker_count / float(fills_total)) or 0.0)
    order_p95 = _percentile(ages, 0.95)
    net_bps = -float(fees_bps_acc)

    # Numeric fields at 6 decimals in output representation responsibility of writer/CLI
    return {
        "fills_total": int(fills_total),
        "net_bps": float(f"{net_bps:.6f}"),
        "taker_share_pct": float(f"{taker_share_pct:.6f}"),
        "order_age_p95_ms": float(f"{order_p95:.6f}"),
        "fees_bps": float(f"{fees_bps_acc:.6f}"),
        "turnover_usd": float(f"{turnover_usd:.6f}"),
    }




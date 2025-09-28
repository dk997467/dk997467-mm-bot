from typing import Dict, Any, Tuple
import json
from pathlib import Path

from src.sim.broker import SimBroker
from src.sim.fill_models import fill_conservative, fill_queue_aware
from src.common.artifacts import write_json_atomic
from src.common.version import utc_now_str, VERSION


def _percentile(values, p):
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


def run_sim(events_path: str, mode: str, params: Dict[str, Any], out_json: str) -> Dict[str, Any]:
    # State
    broker = SimBroker()
    fills_total = 0
    taker_share = 0.0
    net_bps = 0.0
    fees_bps_acc = 0.0
    turnover_usd = 0.0
    ages = []
    qpos = float(params.get("queue", {}).get("initial_qpos_ratio", 0.5))
    qpen = float(params.get("queue", {}).get("queue_penalty_bps", 0.8))

    # Read events
    evs = []
    with open(events_path, 'r', encoding='ascii', newline='\n') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            evs.append(json.loads(line))

    # Process
    book = {"bid": 0.0, "ask": 0.0}
    created_ts: Dict[str, int] = {}
    for ev in evs:
        t = int(ev.get('ts_ms', 0))
        typ = ev.get('type')
        if typ == 'book':
            book['bid'] = float(ev.get('bid', 0.0))
            book['ask'] = float(ev.get('ask', 0.0))
        elif typ == 'place':
            cid = ev['cl_id']
            sym = ev['symbol']
            side = ev['side']
            price = float(ev['price'])
            size = float(ev['size'])
            if broker.place(cid, sym, side, price, size, t):
                created_ts[cid] = t
        elif typ == 'replace':
            cid = ev['cl_id']
            price = ev.get('price')
            size = ev.get('size')
            broker.replace(cid, price, size, t)
        elif typ == 'cancel':
            cid = ev['cl_id']
            broker.cancel(cid, t)

        # Try fills on every tick/update deterministically
        # Evaluate active orders against current book
        for cid, o in list(broker.active().items()):
            order = {
                'cl_id': o.cl_id,
                'symbol': o.symbol,
                'side': o.side,
                'price': o.price,
                'size': o.size,
            }
            if mode == 'conservative':
                filled, fees_bps = fill_conservative(order, book)
                if filled > 0.0:
                    broker.fill(cid, t)
                    fills_total += 1
                    fees_bps_acc += fees_bps
                    turnover_usd += o.price * filled
                    # taker_share approximated by crossing
                    taker_share += 1.0
                    age = max(0, t - created_ts.get(cid, t))
                    ages.append(age)
            else:
                filled, qpos_next, fees_bps = fill_queue_aware(order, book, qpos, {"queue_penalty_bps": qpen})
                qpos = qpos_next
                if filled > 0.0:
                    broker.fill(cid, t)
                    fills_total += 1
                    fees_bps_acc += fees_bps
                    turnover_usd += o.price * filled
                    taker_share += 1.0 * (1.0 if order['side'].lower() == 'buy' and order['price'] >= book['ask'] else 1.0 if order['side'].lower() == 'sell' and order['price'] <= book['bid'] else 0.0)
                    age = max(0, t - created_ts.get(cid, t))
                    ages.append(age)

    # Aggregate
    taker_share_pct = 100.0 * (fills_total and (taker_share / float(fills_total)) or 0.0)
    order_p95 = _percentile(ages, 0.95)
    # net_bps simplistic: -fees minus nothing else (no pnl modeling)
    net_bps = -float(fees_bps_acc)

    report = {
        "fills_total": int(fills_total),
        "net_bps": float(f"{net_bps:.6f}"),
        "taker_share_pct": float(f"{taker_share_pct:.6f}"),
        "order_age_p95_ms": float(f"{order_p95:.6f}"),
        "fees_bps": float(f"{fees_bps_acc:.6f}"),
        "turnover_usd": float(f"{turnover_usd:.6f}"),
        "runtime": {"utc": utc_now_str(), "version": VERSION, "mode": "sim"},
    }
    write_json_atomic(out_json, report)
    return report



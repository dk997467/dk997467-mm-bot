import json
import math
import os
from typing import Any, Dict, Iterable, List, Tuple


def _finite(x: Any) -> float:
    try:
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, 'r', encoding='ascii') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            d = json.loads(line)
            out.append(d)
    return out


def _sign(side: str) -> int:
    return 1 if str(side).upper().startswith('B') else -1


def _nearest_quote(quotes: Dict[str, List[Tuple[int, float, float]]], symbol: str, ts_ms: int) -> Tuple[float, float]:
    arr = quotes.get(symbol, [])
    best = None
    for t, bid, ask in arr:
        if t <= ts_ms:
            best = (bid, ask)
        else:
            break
    if best is None:
        return (0.0, 0.0)
    return best


def _agg_symbols(trades: List[Dict[str, Any]], quotes_idx: Dict[str, List[Tuple[int, float, float]]]) -> Dict[str, Dict[str, float]]:
    by: Dict[str, Dict[str, Any]] = {}
    for tr in trades:
        sym = str(tr.get('symbol', ''))
        if not sym:
            continue
        side = str(tr.get('side', ''))
        sgn = _sign(side)
        price = _finite(tr.get('price', 0.0))
        qty = _finite(tr.get('qty', 0.0))
        mid_before = _finite(tr.get('mid_before', 0.0))
        mid_after_1s = _finite(tr.get('mid_after_1s', 0.0))
        fee_bps = _finite(tr.get('fee_bps', 0.0))
        ts_ms = int(_finite(tr.get('ts_ms', 0)))

        if mid_before <= 0.0:
            continue

        # init
        d = by.setdefault(sym, {
            'gross_bps_sum': 0.0,
            'fees_eff_bps_sum': 0.0,
            'adverse_bps_sum': 0.0,
            'slippage_bps_sum': 0.0,
            'inventory_bps_sum': 0.0,  # We'll compute per-trade proxy and average
            'fills': 0.0,
            'turnover_usd': 0.0,
            'inv_abs_sum': 0.0,
            'notional_sum': 0.0,
        })

        # gross
        gross_bps = sgn * (price - mid_before) / mid_before * 1e4
        # adverse
        adverse_bps = sgn * (mid_after_1s - mid_before) / mid_before * 1e4
        # slippage vs quote at ts
        bid, ask = _nearest_quote(quotes_idx, sym, ts_ms)
        q_ref = bid if sgn < 0 else ask
        if q_ref <= 0.0:
            slip_bps = 0.0
        else:
            slip_bps = sgn * (price - q_ref) / q_ref * 1e4

        notional = abs(price * qty)
        inv_abs = abs(qty)

        d['gross_bps_sum'] += _finite(gross_bps)
        d['fees_eff_bps_sum'] += _finite(fee_bps)
        d['adverse_bps_sum'] += _finite(adverse_bps)
        d['slippage_bps_sum'] += _finite(slip_bps)
        d['fills'] += 1.0
        d['turnover_usd'] += _finite(notional)
        d['inv_abs_sum'] += _finite(inv_abs)
        d['notional_sum'] += _finite(notional)

    # finalize inventory proxy: k=1.0bps * avg(|inv|)/avg(notional) guarded
    out: Dict[str, Dict[str, float]] = {}
    for sym in sorted(by.keys()):
        d = by[sym]
        n = max(1.0, d['fills'])
        avg_inv = d['inv_abs_sum'] / n
        avg_notional = d['notional_sum'] / n
        inv_bps = 0.0
        if avg_notional > 0.0:
            inv_bps = 1.0 * (avg_inv / avg_notional)
        out[sym] = {
            'adverse_bps': _finite(d['adverse_bps_sum'] / n),
            'fees_eff_bps': _finite(d['fees_eff_bps_sum'] / n),
            'fills': float(int(d['fills'])),
            'gross_bps': _finite(d['gross_bps_sum'] / n),
            'inventory_bps': _finite(inv_bps),
            'slippage_bps': _finite(d['slippage_bps_sum'] / n),
            'turnover_usd': _finite(d['turnover_usd']),
        }
        out[sym]['net_bps'] = _finite(
            out[sym]['gross_bps']
            - out[sym]['fees_eff_bps']
            - out[sym]['adverse_bps']
            - out[sym]['slippage_bps']
            - out[sym]['inventory_bps']
        )
    return out


def _index_quotes(quotes: List[Dict[str, Any]]) -> Dict[str, List[Tuple[int, float, float]]]:
    idx: Dict[str, List[Tuple[int, float, float]]] = {}
    for q in quotes:
        sym = str(q.get('symbol', ''))
        if not sym:
            continue
        ts = int(_finite(q.get('ts_ms', 0)))
        bid = _finite(q.get('best_bid', 0.0))
        ask = _finite(q.get('best_ask', 0.0))
        idx.setdefault(sym, []).append((ts, bid, ask))
    # sort by ts
    for sym in idx:
        idx[sym].sort(key=lambda x: x[0])
    return idx


def build_report(trades_path: str, quotes_path: str) -> Dict[str, Any]:
    trades = read_jsonl(trades_path)
    quotes = read_jsonl(quotes_path)
    qidx = _index_quotes(quotes)
    symbols = _agg_symbols(trades, qidx)

    # totals as average over symbols for bps fields, sum for fills/turnover
    if symbols:
        bps_keys = ['gross_bps','fees_eff_bps','adverse_bps','slippage_bps','inventory_bps','net_bps']
        tot: Dict[str, float] = {k: 0.0 for k in bps_keys}
        fills = 0.0
        turn = 0.0
        for s in symbols.values():
            for k in bps_keys:
                tot[k] += _finite(s.get(k, 0.0))
            fills += _finite(s.get('fills', 0.0))
            turn += _finite(s.get('turnover_usd', 0.0))
        n = float(len(symbols))
        total = {k: _finite(tot[k] / n) for k in bps_keys}
        total['fills'] = float(int(fills))
        total['turnover_usd'] = _finite(turn)
    else:
        total = {
            'adverse_bps': 0.0,
            'fees_eff_bps': 0.0,
            'fills': 0.0,
            'gross_bps': 0.0,
            'inventory_bps': 0.0,
            'net_bps': 0.0,
            'slippage_bps': 0.0,
            'turnover_usd': 0.0,
        }

    runtime = {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'}
    report: Dict[str, Any] = {
        'runtime': runtime,
        'symbols': {k: symbols[k] for k in sorted(symbols.keys())},
        'total': total,
    }
    return report


def write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)



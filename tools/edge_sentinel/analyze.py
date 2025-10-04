import argparse
import json
import os
from typing import Any, Dict, List, Tuple


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    out = []
    with open(path, 'r', encoding='ascii') as f:
        for line in f:
            line = line.strip()  # Remove ALL whitespace (including \r\n on Windows)
            if not line:
                continue
            out.append(json.loads(line))
    return out


def _write_json_atomic(path: str, data: Any) -> None:
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
    try:
        from src.common.eol import normalize_eol  # type: ignore
        normalize_eol(path, style="crlf", ensure_trailing=3)
    except Exception:
        pass


def _bucket_key(ts_ms: int, bucket_min: int) -> str:
    # Align to floor of bucket
    bucket_ms = int(bucket_min) * 60_000
    b = (int(ts_ms) // bucket_ms) * bucket_ms
    import datetime as dt
    # Use timezone-aware datetime to avoid deprecation warning
    return dt.datetime.fromtimestamp(b / 1000, dt.UTC).strftime('%Y-%m-%dT%H:%MZ')


def analyze(trades_path: str, quotes_path: str, bucket_min: int) -> Dict[str, Any]:
    trades = _read_jsonl(trades_path)
    # quotes reserved for future slippage reference; we use embedded slippage proxy in trades
    _ = _read_jsonl(quotes_path)

    by_sym_bucket: Dict[Tuple[str, str], Dict[str, float]] = {}
    per_sym: Dict[str, Dict[str, float]] = {}
    for t in trades:
        sym = str(t.get('symbol'))
        ts_ms = int(_finite(t.get('ts_ms', 0)))
        bkey = _bucket_key(ts_ms, bucket_min)
        key = (sym, bkey)
        d = by_sym_bucket.setdefault(key, {k: 0.0 for k in ['gross_bps','fees_eff_bps','adverse_bps','slippage_bps','inventory_bps','fills','turnover_usd']})
        g = _finite(t.get('gross_bps', 0.0))
        f = _finite(t.get('fee_bps', 0.0))
        adv = _finite(t.get('adverse_bps', 0.0))
        sl = _finite(t.get('slippage_bps', 0.0))
        inv = _finite(t.get('inventory_bps', 0.0))
        qty = _finite(t.get('qty', 0.0))
        price = _finite(t.get('price', 0.0))
        d['gross_bps'] += g
        d['fees_eff_bps'] += f
        d['adverse_bps'] += adv
        d['slippage_bps'] += sl
        d['inventory_bps'] += inv
        d['fills'] += 1.0
        d['turnover_usd'] += abs(price * qty)

        s = per_sym.setdefault(sym, {k: 0.0 for k in ['gross_bps','fees_eff_bps','adverse_bps','slippage_bps','inventory_bps','fills','turnover_usd']})
        for k in s.keys():
            s[k] += d[k] - (s[k] - s[k])  # add latest increment via d's own increments
        s['gross_bps'] += g; s['fees_eff_bps'] += f; s['adverse_bps'] += adv; s['slippage_bps'] += sl; s['inventory_bps'] += inv; s['fills'] += 1.0; s['turnover_usd'] += abs(price*qty)

    # finalize net_bps as averages per bucket/symbol
    sym_bucket_rows: List[Tuple[str, str, Dict[str, float]]] = []
    for (sym, bkey), d in sorted(by_sym_bucket.items(), key=lambda x: (x[0][0], x[0][1])):
        n = max(1.0, d['fills'])
        row = {k: _finite(d[k] / n) for k in ['gross_bps','fees_eff_bps','adverse_bps','slippage_bps','inventory_bps']}
        row['net_bps'] = _finite(row['gross_bps'] - row['fees_eff_bps'] - row['adverse_bps'] - row['slippage_bps'] - row['inventory_bps'])
        row['fills'] = d['fills']
        row['turnover_usd'] = d['turnover_usd']
        sym_bucket_rows.append((sym, bkey, row))

    # ranking
    # top symbols by net drop: ascending net_bps
    sym_agg: Dict[str, float] = {}
    for sym, bkey, row in sym_bucket_rows:
        sym_agg[sym] = sym_agg.get(sym, 0.0) + row['net_bps']
    top_symbols_by_net_drop = [s for s, _ in sorted(sym_agg.items(), key=lambda x: (x[1], x[0]))][:5]
    # top buckets by net drop
    bucket_agg: Dict[str, float] = {}
    for sym, bkey, row in sym_bucket_rows:
        bucket_agg[bkey] = bucket_agg.get(bkey, 0.0) + row['net_bps']
    top_buckets_by_net_drop = [b for b, _ in sorted(bucket_agg.items(), key=lambda x: (x[1], x[0]))][:5]
    # contributors by component
    contributors_by_component: Dict[str, List[str]] = {}
    for comp in ['fees_eff_bps','adverse_bps','slippage_bps','inventory_bps']:
        agg: Dict[str, float] = {}
        for sym, bkey, row in sym_bucket_rows:
            agg[sym] = agg.get(sym, 0.0) + row[comp]
        contributors_by_component[comp] = [s for s, _ in sorted(agg.items(), key=lambda x: (-x[1], x[0]))][:5]

    # advice heuristics
    advice: List[str] = []
    # slippage high and replace rate high -> raise min_interval
    sl_total = sum(max(0.0, r[2]['slippage_bps']) for r in sym_bucket_rows)
    replace_rate_high = True  # placeholder heuristic (no replace data), assume true if slippage is top contributor
    if sl_total > 0 and replace_rate_high:
        advice.append('tune throttle: raise min_interval_ms')
    # adverse high with sigma high -> lower impact cap (no sigma here; use adverse dominance)
    adv_total = sum(max(0.0, r[2]['adverse_bps']) for r in sym_bucket_rows)
    if adv_total > sl_total:
        advice.append('lower micro impact_cap_ratio')
    # fees high near tier+1 -> increase vip tilt cap mildly (no tiers info; if fees dominates gross)
    fees_total = sum(max(0.0, r[2]['fees_eff_bps']) for r in sym_bucket_rows)
    gross_total = sum(max(0.0, r[2]['gross_bps']) for r in sym_bucket_rows)
    if fees_total > 0 and gross_total > 0 and (fees_total / gross_total) > 0.3:
        advice.append('increase vip tilt cap mildly')

    # summary
    summary = {
        'symbols': {sym: {**{k: _finite(v) for k, v in per_sym[sym].items()}, 'net_bps': _finite((per_sym[sym]['gross_bps'] - per_sym[sym]['fees_eff_bps'] - per_sym[sym]['adverse_bps'] - per_sym[sym]['slippage_bps'] - per_sym[sym]['inventory_bps']) / max(1.0, per_sym[sym]['fills']))} for sym in sorted(per_sym.keys())},
        'buckets': [{'symbol': sym, 'bucket': b, **row} for sym, b, row in sym_bucket_rows],
    }

    rep = {
        'advice': advice,
        'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'},
        'summary': summary,
        'top': {
            'contributors_by_component': contributors_by_component,
            'top_buckets_by_net_drop': top_buckets_by_net_drop,
            'top_symbols_by_net_drop': top_symbols_by_net_drop,
        },
    }
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--trades', required=True)
    ap.add_argument('--quotes', required=True)
    ap.add_argument('--bucket-min', type=int, default=15)
    args = ap.parse_args(argv)

    rep = analyze(args.trades, args.quotes, args.bucket_min)
    _write_json_atomic('artifacts/EDGE_SENTINEL.json', rep)
    print('EDGE_SENTINEL WROTE artifacts/EDGE_SENTINEL.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



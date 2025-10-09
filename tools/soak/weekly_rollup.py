import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Ensure src/ is in path for imports
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from src.common.runtime import get_runtime_info


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


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


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='ascii') as f:
        return json.load(f)


def _nearest_rank(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    import math
    rank = max(1, int(math.ceil(q * len(s)))) - 1
    if rank < 0:
        rank = 0
    if rank >= len(s):
        rank = len(s) - 1
    return float(s[rank])


def _median(values: List[float]) -> float:
    return _nearest_rank(values, 0.5)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--soak-dir', required=True)
    ap.add_argument('--ledger', required=True)
    ap.add_argument('--out-json', required=True)
    ap.add_argument('--out-md', required=True)
    args = ap.parse_args(argv)

    # Collect last 7 soak reports by date in filename
    paths = glob.glob(os.path.join(args.soak_dir, 'REPORT_SOAK_*.json'))
    def _date_of(p: str) -> str:
        base = os.path.basename(p)
        try:
            return base.split('REPORT_SOAK_')[1].split('.')[0]
        except Exception:
            return '00000000'
    paths = sorted(paths, key=_date_of)
    paths = paths[-7:]
    reports = []
    dates = []
    for p in paths:
        try:
            d = _read_json(p)
            reports.append(d)
            dates.append(_date_of(p))
        except Exception:
            continue

    # Aggregate metrics
    edge = [_finite(r.get('edge_net_bps', 0.0)) for r in reports]
    lat = [_finite(r.get('order_age_p95_ms', 0.0)) for r in reports]
    tak = [_finite(r.get('taker_share_pct', 0.0)) for r in reports]

    edge_median = _median(edge)
    edge_p25 = _nearest_rank(edge, 0.25)
    edge_p75 = _nearest_rank(edge, 0.75)
    lat_median = _median(lat)
    lat_p90 = _nearest_rank(lat, 0.9)
    tak_median = _median(tak)
    tak_p90 = _nearest_rank(tak, 0.9)

    # Ledger totals over the same dates (match by date)
    ledger = []
    try:
        ledger = _read_json(args.ledger)
    except Exception:
        ledger = []
    date_set = set([f'{d[:4]}-{d[4:6]}-{d[6:8]}' for d in dates])
    ledger_week = [x for x in ledger if str(x.get('date', '')) in date_set]
    equity_first = _finite(ledger_week[0].get('equity', 0.0)) if ledger_week else 0.0
    equity_last = _finite(ledger_week[-1].get('equity', 0.0)) if ledger_week else 0.0
    # Round to 10 decimal places to avoid floating point representation differences
    # between Python 3.11 (0.6) and 3.13 (0.6000000000000001)
    fees_sum = round(sum(_finite(x.get('fees', 0.0)) for x in ledger_week), 10)
    rebates_sum = round(sum(_finite(x.get('rebates', 0.0)) for x in ledger_week), 10)

    # Prev week trends
    prev_path = os.path.join(os.path.dirname(args.out_json), 'WEEKLY_ROLLUP_prev.json')
    if os.path.exists(prev_path):
        prev = _read_json(prev_path)
        prev_edge = _finite(((prev.get('edge_net_bps') or {}).get('median', 0.0)))
        prev_lat = _finite(((prev.get('order_age_p95_ms') or {}).get('median', 0.0)))
        prev_tak = _finite(((prev.get('taker_share_pct') or {}).get('median', 0.0)))
        trend_edge = edge_median - prev_edge
        trend_lat = lat_median - prev_lat
        trend_tak = tak_median - prev_tak
        # Trend ok if not worse than 10%
        trend_ok = True
        if prev_edge > 0 and edge_median < prev_edge * 0.9:
            trend_ok = False
        if prev_lat > 0 and lat_median > prev_lat * 1.1:
            trend_ok = False
        if prev_tak > 0 and tak_median > prev_tak * 1.1:
            trend_ok = False
    else:
        trend_edge = 0.0
        trend_lat = 0.0
        trend_tak = 0.0
        trend_ok = True

    # Guards
    edge_ok = (edge_median >= 2.5)
    latency_ok = (lat_p90 <= 350.0) or (lat_median <= 350.0)
    taker_ok = (tak_median <= 15.0)
    guards = {
        'edge_ok': bool(edge_ok),
        'latency_ok': bool(latency_ok),
        'taker_ok': bool(taker_ok),
        'trend_ok': bool(trend_ok),
    }
    if edge_ok and latency_ok and taker_ok and trend_ok:
        verdict = 'GO'
    elif edge_ok and latency_ok and taker_ok and not trend_ok:
        verdict = 'WARN'
    else:
        verdict = 'NO-GO'

    period = {'from': '', 'to': ''}
    if dates:
        f = dates[0]
        t = dates[-1]
        period = {'from': f'{f[:4]}-{f[4:6]}-{f[6:8]}', 'to': f'{t[:4]}-{t[4:6]}-{t[6:8]}'}

    report = {
        'edge_net_bps': {'median': edge_median, 'p25': edge_p25, 'p75': edge_p75, 'trend_vs_prev_week_bps': trend_edge},
        'ledger': {'equity_change_eur': (equity_last - equity_first), 'fees_eur': fees_sum, 'rebates_eur': rebates_sum},
        'order_age_p95_ms': {'median': lat_median, 'p90': lat_p90, 'trend_vs_prev_week_ms': trend_lat},
        'period': period,
        'regress_guard': guards,
        'runtime': get_runtime_info(),
        'taker_share_pct': {'median': tak_median, 'p90': tak_p90, 'trend_vs_prev_week_pct': trend_tak},
        'verdict': verdict,
    }

    _write_json_atomic(args.out_json, report)
    # MD
    lines = []
    lines.append('WEEKLY SOAK ROLLUP\n')
    lines.append('\n')
    lines.append('| metric | v1 | v2 | v3 |\n')
    lines.append('|--------|----|----|----|\n')
    lines.append('| edge_net_bps | %.6f | %.6f | %.6f |\n' % (edge_median, edge_p25, edge_p75))
    lines.append('| order_age_p95_ms | %.6f | %.6f |  |\n' % (lat_median, lat_p90))
    lines.append('| taker_share_pct | %.6f | %.6f |  |\n' % (tak_median, tak_p90))
    lines.append('| ledger_equity_change_eur | %.6f | fees=%.6f | rebates=%.6f |\n' % (report['ledger']['equity_change_eur'], report['ledger']['fees_eur'], report['ledger']['rebates_eur']))
    lines.append('\n')
    lines.append('Verdict: ' + verdict + '\n')
    md = ''.join(lines)
    # write md
    os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
    tmp = args.out_md + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write(md)
        if not md.endswith('\n'):
            f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(args.out_md):
        os.replace(tmp, args.out_md)
    else:
        os.rename(tmp, args.out_md)

    print('WEEKLY_ROLLUP WROTE', args.out_json, args.out_md)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



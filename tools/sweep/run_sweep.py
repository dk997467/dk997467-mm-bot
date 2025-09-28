import argparse
import json
import os
from itertools import product
from typing import Any, Dict, List

import yaml


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


def _read_events(path: str) -> List[Dict[str, Any]]:
    ev = []
    with open(path, 'r', encoding='ascii') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            ev.append(json.loads(line))
    return ev


def _simulate(events: List[Dict[str, Any]], p: Dict[str, float]) -> Dict[str, float]:
    # Simplified deterministic model
    max_delta_ratio = _finite(p['max_delta_ratio'])
    impact_cap_ratio = _finite(p['impact_cap_ratio'])
    min_interval_ms = _finite(p['min_interval_ms'])
    tail_age_ms = _finite(p['tail_age_ms'])

    # base metrics from events
    base_net = 3.0
    base_p95 = 320.0
    base_fill = 0.70
    base_replace = 300.0

    # effects: increasing min_interval reduces replace and p95, may reduce net slightly
    k_int = (min_interval_ms - 60.0) / 40.0  # 0 at 60, 0.5 at 80, 1.0 at 100
    replace = max(0.0, base_replace * (1.0 - 0.4 * k_int))
    p95 = max(0.0, base_p95 * (1.0 - 0.1 * k_int))
    net = base_net * (1.0 - 0.05 * k_int)

    # tail_age: lower tail reduces p95 a bit and increases fill
    k_tail = (800.0 - tail_age_ms) / 200.0  # 0 at 800, 0.5 at 700, 1.0 at 600
    p95 = max(0.0, p95 * (1.0 - 0.05 * k_tail))
    fill = min(1.0, base_fill * (1.0 + 0.05 * k_tail))

    # impact cap: lower cap reduces net a bit but improves stability of p95
    k_imp = (0.10 - impact_cap_ratio) / 0.04  # 0 at 0.10, 1 at 0.06
    net = net * (1.0 - 0.03 * k_imp)
    p95 = p95 * (1.0 - 0.02 * k_imp)

    # max_delta_ratio: lower reduces net slightly but improves p95
    k_delta = (0.15 - max_delta_ratio) / 0.05  # 0 at 0.15, 1 at 0.10
    net = net * (1.0 - 0.04 * k_delta)
    p95 = p95 * (1.0 - 0.03 * k_delta)

    return {
        'net_bps': _finite(net),
        'order_age_p95_ms': _finite(p95),
        'fill_rate': _finite(fill),
        'replace_rate_per_min': _finite(replace),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--events', required=True)
    ap.add_argument('--grid', required=True)
    ap.add_argument('--out-json', required=True)
    args = ap.parse_args(argv)

    with open(args.grid, 'r', encoding='ascii') as f:
        grid_all = yaml.safe_load(f)
    grid = {
        'max_delta_ratio': grid_all['allocator.smoothing.max_delta_ratio'],
        'impact_cap_ratio': grid_all['signals.impact_cap_ratio'],
        'min_interval_ms': grid_all['latency_boost.replace.min_interval_ms'],
        'tail_age_ms': grid_all['latency_boost.tail_batch.tail_age_ms'],
    }

    events = _read_events(args.events)
    results: List[Dict[str, Any]] = []
    for combo in product(grid['max_delta_ratio'], grid['impact_cap_ratio'], grid['min_interval_ms'], grid['tail_age_ms']):
        params = {
            'max_delta_ratio': float(combo[0]),
            'impact_cap_ratio': float(combo[1]),
            'min_interval_ms': float(combo[2]),
            'tail_age_ms': float(combo[3]),
        }
        metrics = _simulate(events, params)
        results.append({'params': params, 'metrics': metrics})

    # sort by net desc then p95 asc for determinism
    results.sort(key=lambda x: (-x['metrics']['net_bps'], x['metrics']['order_age_p95_ms']))
    # filter safe
    safe = [r for r in results if (r['metrics']['order_age_p95_ms'] <= 350.0)]
    top3 = safe[:3]

    rep = {
        'grid': grid,
        'results': results,
        'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'},
        'top3_by_net_bps_safe': top3,
    }
    _write_json_atomic(args.out_json, rep)
    print('PARAM_SWEEP WROTE', args.out_json)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



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


def _median(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    s = sorted(values)
    m = n // 2
    if n % 2 == 1:
        return s[m]
    return (s[m - 1] + s[m]) / 2.0


def _p95(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    s = sorted(values)
    # nearest-rank method
    rank = max(1, int(math.ceil(0.95 * n))) - 1
    return s[min(rank, n - 1)]


def parse_jsonl(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, 'r', encoding='ascii') as f:
        for line in f:
            line = line.strip('\n')
            if not line:
                continue
            d = json.loads(line)
            # Normalize
            d['region'] = str(d.get('region', ''))
            d['window'] = str(d.get('window', ''))
            d['net_bps'] = _finite(d.get('net_bps', 0.0))
            d['order_age_p95_ms'] = _finite(d.get('order_age_p95_ms', 0.0))
            d['fill_rate'] = _finite(d.get('fill_rate', 0.0))
            d['taker_share_pct'] = _finite(d.get('taker_share_pct', 0.0))
            out.append(d)
    return out


def _aggregate(records: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
    by_region: Dict[str, Dict[str, List[float]]] = {}
    by_window: Dict[str, Dict[str, List[float]]] = {}
    for r in records:
        reg = r['region']
        win = r['window']
        for tgt, key in ((by_region, reg), (by_window, win)):
            d = tgt.setdefault(key, {
                'net_bps': [],
                'order_age_p95_ms': [],
                'fill_rate': [],
                'taker_share_pct': [],
            })
            d['net_bps'].append(_finite(r['net_bps']))
            d['order_age_p95_ms'].append(_finite(r['order_age_p95_ms']))
            d['fill_rate'].append(_finite(r['fill_rate']))
            d['taker_share_pct'].append(_finite(r['taker_share_pct']))

    def finalize(m: Dict[str, Dict[str, List[float]]]) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for k in sorted(m.keys()):
            vals = m[k]
            out[k] = {
                'fill_rate': _median(vals['fill_rate']),
                'net_bps': _median(vals['net_bps']),
                'order_age_p95_ms': _p95(vals['order_age_p95_ms']),
                'taker_share_pct': _median(vals['taker_share_pct']),
            }
        return out

    return finalize(by_region), finalize(by_window)


def _validate_regions_cfg(cfg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    regions = cfg.get('regions', [])
    names = [r.get('name') for r in regions]
    if len(names) != len(set(names)):
        raise ValueError('E_REGIONS_CFG:duplicate_names')
    for r in regions:
        if r.get('enabled') not in (True, False):
            raise ValueError('E_REGIONS_CFG:enabled_bool')
    metrics = cfg.get('metrics', {})
    keys = metrics.get('keys', [])
    for k in ('net_bps','order_age_p95_ms','fill_rate','taker_share_pct'):
        if k not in keys:
            raise ValueError('E_REGIONS_CFG:missing_metric_key:' + k)
    switch = cfg.get('switch', {})
    safe = switch.get('safe_thresholds', {})
    if 'cooldown_s' not in switch:
        raise ValueError('E_REGIONS_CFG:missing_cooldown')
    return regions, metrics, {'safe': safe, 'cooldown_s': int(switch['cooldown_s'])}


def compare(records: List[Dict[str, Any]], regions_cfg: Dict[str, Any], safe_cfg: Dict[str, Any]) -> Dict[str, Any]:
    by_region, _ = _aggregate(records)

    def is_safe(m: Dict[str, float]) -> bool:
        return (
            _finite(m.get('net_bps')) >= _finite(safe_cfg.get('net_bps_min', 0.0)) and
            _finite(m.get('order_age_p95_ms')) <= _finite(safe_cfg.get('order_age_p95_ms_max', float('inf'))) and
            _finite(m.get('taker_share_pct')) <= _finite(safe_cfg.get('taker_share_pct_max', float('inf')))
        )

    # Choose winner among enabled regions, considering windows; pick best (region, window)
    winner_pair = None
    best_net = -1e18
    best_latency = float('inf')
    enabled = {r['name'] for r in regions_cfg if r.get('enabled')}

    # Build per (region,window) metrics by joining medians; for simplicity, use region-level stats for ranking windows independently
    # We instead aggregate per (region,window) directly from records:
    by_rw: Dict[Tuple[str, str], Dict[str, float]] = {}
    tmp: Dict[Tuple[str, str], Dict[str, List[float]]] = {}
    for r in records:
        key = (r['region'], r['window'])
        d = tmp.setdefault(key, {'net_bps': [], 'order_age_p95_ms': [], 'fill_rate': [], 'taker_share_pct': []})
        d['net_bps'].append(_finite(r['net_bps']))
        d['order_age_p95_ms'].append(_finite(r['order_age_p95_ms']))
        d['fill_rate'].append(_finite(r['fill_rate']))
        d['taker_share_pct'].append(_finite(r['taker_share_pct']))
    for k in tmp:
        vals = tmp[k]
        by_rw[k] = {
            'net_bps': _median(vals['net_bps']),
            'order_age_p95_ms': _p95(vals['order_age_p95_ms']),
            'fill_rate': _median(vals['fill_rate']),
            'taker_share_pct': _median(vals['taker_share_pct']),
        }

    for (reg, win), m in sorted(by_rw.items(), key=lambda x: (x[0][0], x[0][1])):
        if reg not in enabled:
            continue
        if not is_safe(m):
            continue
        net = _finite(m['net_bps'])
        lat = _finite(m['order_age_p95_ms'])
        if net > best_net or (net == best_net and lat < best_latency):
            best_net = net
            best_latency = lat
            winner_pair = (reg, win)

    # Prepare outputs
    from tools.finops.reconcile import _runtime_meta as _runtime_meta_from_art
    # runtime is not from artifacts here; provide stable default
    runtime = {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'}

    regions_out = {k: by_region[k] for k in sorted(by_region.keys())}
    # Windows aggregated using only enabled regions
    win_tmp: Dict[str, Dict[str, List[float]]] = {}
    for r in records:
        if r['region'] not in enabled:
            continue
        ww = r['window']
        d = win_tmp.setdefault(ww, {'net_bps': [], 'order_age_p95_ms': [], 'fill_rate': [], 'taker_share_pct': []})
        d['net_bps'].append(_finite(r['net_bps']))
        d['order_age_p95_ms'].append(_finite(r['order_age_p95_ms']))
        d['fill_rate'].append(_finite(r['fill_rate']))
        d['taker_share_pct'].append(_finite(r['taker_share_pct']))
    windows_out: Dict[str, Dict[str, float]] = {}
    for w in sorted(win_tmp.keys()):
        vals = win_tmp[w]
        windows_out[w] = {
            'fill_rate': _median(vals['fill_rate']),
            'net_bps': _median(vals['net_bps']),
            'order_age_p95_ms': _p95(vals['order_age_p95_ms']),
            'taker_share_pct': _median(vals['taker_share_pct']),
        }
    report = {
        'regions': regions_out,
        'runtime': runtime,
        'windows': windows_out,
        'winner': {'region': winner_pair[0], 'window': winner_pair[1]} if winner_pair else {'region': '', 'window': ''},
    }
    return report



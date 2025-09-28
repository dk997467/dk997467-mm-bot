import json
import os
from typing import Any, Dict, List


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


def _median(vals: List[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    import math
    idx = max(0, int(math.ceil(0.5 * len(s))) - 1)
    if idx >= len(s):
        idx = len(s) - 1
    return float(s[idx])


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
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


def _write_text_atomic(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write(content)
        if not content.endswith('\n'):
            f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def check(today_report: Dict[str, Any], last7_reports: List[Dict[str, Any]], thresholds: Dict[str, float] = None) -> Dict[str, Any]:
    thr = thresholds or {'edge_drop_pct': 10.0, 'latency_rise_pct': 10.0, 'taker_rise_pct': 10.0}
    e_med = _median([_finite(r.get('edge_net_bps', 0.0)) for r in last7_reports])
    l_med = _median([_finite(r.get('order_age_p95_ms', 0.0)) for r in last7_reports])
    t_med = _median([_finite(r.get('taker_share_pct', 0.0)) for r in last7_reports])

    edge_today = _finite(today_report.get('edge_net_bps', 0.0))
    lat_today = _finite(today_report.get('order_age_p95_ms', 0.0))
    tak_today = _finite(today_report.get('taker_share_pct', 0.0))

    ok = True
    reason = 'NONE'
    if edge_today < e_med * (1.0 - _finite(thr.get('edge_drop_pct', 10.0)) / 100.0):
        ok = False; reason = 'EDGE_REG'
    elif lat_today > l_med * (1.0 + _finite(thr.get('latency_rise_pct', 10.0)) / 100.0):
        ok = False; reason = 'LAT_REG'
    elif tak_today > t_med * (1.0 + _finite(thr.get('taker_rise_pct', 10.0)) / 100.0):
        ok = False; reason = 'TAKER_REG'

    baseline = {'edge_med': e_med, 'p95_med': l_med, 'taker_med': t_med}

    if not ok:
        payload = {'baseline': baseline, 'reason': reason, 'today': {'edge_net_bps': edge_today, 'order_age_p95_ms': lat_today, 'taker_share_pct': tak_today}}
        _write_json_atomic('artifacts/REG_GUARD_STOP.json', payload)
        _write_text_atomic('artifacts/REG_GUARD_STOP.md', 'REG_GUARD STOP\nreason=' + reason + '\n')

    return {'ok': ok, 'reason': reason, 'baseline': baseline}



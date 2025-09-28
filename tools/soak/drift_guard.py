import json
import os
from datetime import datetime, timezone
from typing import Any, Dict


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='ascii') as f:
        return json.load(f)


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
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def check(report_edge_json: str) -> Dict[str, Any]:
    ok = True
    reason = 'NONE'
    snap: Dict[str, Any] = {}
    try:
        edge = _read_json(report_edge_json)
    except Exception:
        edge = {}
    total = edge.get('total', {}) if isinstance(edge, dict) else {}
    net = _finite(total.get('net_bps', 0.0))
    # Latency and taker share from edge if present, else try artifacts/metrics.json
    lat = _finite(total.get('order_age_p95_ms', 0.0))
    tak = _finite(total.get('taker_share_pct', 0.0))
    if lat == 0.0 or tak == 0.0:
        try:
            met = _read_json('artifacts/metrics.json')
        except Exception:
            met = {}
        lat = lat or _finite(((met.get('pnl') or {}).get('total_order_age_p95_ms', 0.0)))
        tak = tak or _finite(((met.get('pnl') or {}).get('total_taker_share_pct', 0.0)))

    if net < 2.5:
        ok = False
        reason = 'DRIFT_EDGE'
    elif lat > 350.0:
        ok = False
        reason = 'DRIFT_LAT'
    elif tak > 15.0:
        ok = False
        reason = 'DRIFT_TAKER'

    snap = {'net_bps': net, 'order_age_p95_ms': lat, 'taker_share_pct': tak}

    if not ok:
        payload = {'reason': reason, 'snapshot': snap, 'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
        _write_json_atomic('artifacts/DRIFT_STOP.json', payload)
        md = 'DRIFT STOP\n\nreason=' + reason + '\n'
        _write_text_atomic('artifacts/DRIFT_STOP.md', md)

    return {'ok': ok, 'reason': reason, 'snapshot': snap}



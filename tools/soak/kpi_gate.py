import json
import os


def _finite(x):
    try:
        import math
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except Exception:
        return 0.0


def _write_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def main(argv=None) -> int:
    with open('artifacts/WEEKLY_ROLLUP.json', 'r', encoding='ascii') as f:
        wk = json.load(f)
    edge_med = _finite(((wk.get('edge_net_bps') or {}).get('median', 0.0)))
    lat_med = _finite(((wk.get('order_age_p95_ms') or {}).get('median', 0.0)))
    tak_med = _finite(((wk.get('taker_share_pct') or {}).get('median', 0.0)))
    trend_ok = bool(((wk.get('regress_guard') or {}).get('trend_ok', True)))

    edge_ok = edge_med >= 2.5
    lat_ok = lat_med <= 350.0
    tak_ok = tak_med <= 15.0

    reasons = []
    if not edge_ok:
        reasons.append('EDGE')
    if not lat_ok:
        reasons.append('LAT')
    if not tak_ok:
        reasons.append('TAKER')
    if not trend_ok:
        reasons.append('TREND')

    if edge_ok and lat_ok and tak_ok and trend_ok:
        verdict = 'PASS'
    elif edge_ok and lat_ok and tak_ok and not trend_ok:
        verdict = 'WARN'
    else:
        verdict = 'FAIL'

    rep = {
        'reasons': reasons,
        'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'},
        'verdict': verdict,
    }
    _write_json_atomic('artifacts/KPI_GATE.json', rep)
    md = 'KPI GATE\n\nVerdict: ' + verdict + (' (' + ','.join(reasons) + ')' if reasons else '') + '\n'
    path = 'artifacts/KPI_GATE.md'
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write(md)
        if not md.endswith('\n'):
            f.write('\n')
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)
    print('KPI_GATE', verdict)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



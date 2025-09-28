import argparse
import json
import os
from typing import Any, Dict, List


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except Exception:
        return 0.0


def _median(xs: List[float]) -> float:
    ys = sorted(_finite(x) for x in xs)
    n = len(ys)
    if n == 0:
        return 0.0
    m = n // 2
    if n % 2 == 1:
        return ys[m]
    return (ys[m - 1] + ys[m]) / 2.0


def _mad(xs: List[float]) -> float:
    med = _median(xs)
    dev = [abs(_finite(x) - med) for x in xs]
    return _median(dev)


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    import os
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


def _write_text_atomic(path: str, content: str) -> None:
    import os
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


def _load_edge_buckets(path: str) -> List[Dict[str, Any]]:
    with open(path, 'r', encoding='ascii') as f:
        rep = json.load(f)
    # Expecting {"buckets":[{"bucket":"HH:MM","net_bps":...,"order_age_p95_ms":...,"taker_share_pct":...}, ...]}
    return list(rep.get('buckets') or [])


def detect_anomalies(buckets: List[Dict[str, Any]], k: float = 3.0) -> List[Dict[str, Any]]:
    hhmm = [str(b.get('bucket', '')) for b in buckets]
    net = [_finite(b.get('net_bps', 0.0)) for b in buckets]
    p95 = [_finite(b.get('order_age_p95_ms', 0.0)) for b in buckets]
    tak = [_finite(b.get('taker_share_pct', 0.0)) for b in buckets]

    med_net, mad_net = _median(net), _mad(net)
    med_p95, mad_p95 = _median(p95), _mad(p95)
    med_tak, mad_tak = _median(tak), _mad(tak)

    out: List[Dict[str, Any]] = []
    for i in range(len(buckets)):
        b = hhmm[i]
        # EDGE (drop)
        if net[i] < (med_net - k * mad_net):
            out.append({'bucket': b, 'kind': 'EDGE', 'value': net[i], 'med': med_net, 'mad': mad_net})
        # LAT (rise)
        if p95[i] > (med_p95 + k * mad_p95):
            out.append({'bucket': b, 'kind': 'LAT', 'value': p95[i], 'med': med_p95, 'mad': mad_p95})
        # TAKER (rise)
        if tak[i] > (med_tak + k * mad_tak):
            out.append({'bucket': b, 'kind': 'TAKER', 'value': tak[i], 'med': med_tak, 'mad': mad_tak})

    # deterministic order: by bucket asc, kind order EDGE < LAT < TAKER
    order = {'EDGE': 0, 'LAT': 1, 'TAKER': 2}
    out.sort(key=lambda x: (str(x['bucket']), order.get(str(x['kind']), 9), float(x['value'])))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--edge-report', required=True)
    ap.add_argument('--bucket-min', type=int, default=15)
    ap.add_argument('--out-json', default='artifacts/ANOMALY_RADAR.json')
    args = ap.parse_args(argv)

    buckets = _load_edge_buckets(args.edge_report)
    anomalies = detect_anomalies(buckets, 3.0)
    rep = {
        'anomalies': anomalies,
        'bucket_minutes': int(args.bucket_min),
        'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'},
    }
    # Deterministic artifact writer with rounding + CRLF+3
    try:
        from src.common.jsonio import dump_json_artifact  # type: ignore
        dump_json_artifact(args.out_json, rep)
    except Exception:
        # Fallback to previous atomic writer
        _write_json_atomic(args.out_json, rep)
        try:
            from src.common.eol import normalize_eol  # type: ignore
            normalize_eol(args.out_json, style="crlf", ensure_trailing=3)
        except Exception:
            pass

    # Render MD
    md_path = os.path.splitext(args.out_json)[0] + '.md'
    lines: List[str] = []
    lines.append('ANOMALY RADAR\n')
    lines.append('\n')
    lines.append('| bucket | kind | value | med | mad |\n')
    lines.append('|--------|------|-------|-----|-----|\n')
    for a in anomalies:
        lines.append('| ' + str(a['bucket']) + ' | ' + str(a['kind']) + ' | ' + ('%.6f' % float(a['value'])) + ' | ' + ('%.6f' % float(a['med'])) + ' | ' + ('%.6f' % float(a['mad'])) + ' |\n')
    # Advice (1-3)
    kinds = {str(a['kind']) for a in anomalies}
    advice: List[str] = []
    if 'EDGE' in kinds:
        advice.append('check edge breakdown: gross/fees/adverse/slippage on buckets')
    if 'LAT' in kinds:
        advice.append('investigate queue p95: run bench_queue baseline vs tuned')
    if 'TAKER' in kinds:
        advice.append('re-check taker caps/routing and fees settings')
    if advice:
        lines.append('\n')
        lines.append('What to do:\n')
        for s in advice[:3]:
            lines.append('- ' + s + '\n')
    _write_text_atomic(md_path, ''.join(lines))
    try:
        from src.common.eol import normalize_eol  # type: ignore
        normalize_eol(md_path, style="crlf", ensure_trailing=3)
    except Exception:
        pass

    print('ANOMALY_RADAR', args.out_json)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



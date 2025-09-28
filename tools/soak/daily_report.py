import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def _finite(x: Any) -> float:
    try:
        import math
        v = float(x)
        if math.isfinite(v):
            return v
        return 0.0
    except Exception:
        return 0.0


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, 'r', encoding='ascii') as f:
            return json.load(f)
    except Exception:
        return None


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


def _find_latest_soak_reconcile() -> Optional[str]:
    base = Path('dist/finops/soak')
    if not base.exists():
        return None
    candidates = []
    for d in base.iterdir():
        if d.is_dir():
            p = d / 'reconcile_report.json'
            if p.exists():
                candidates.append(str(p))
    return candidates[-1] if candidates else None


def _verdict(edge_net: float, latency: float, taker: float) -> str:
    # Thresholds
    ok = (edge_net >= 2.5 and latency <= 350.0 and taker <= 15.0)
    warn = (
        edge_net >= 2.5 * 0.9 and latency <= 350.0 * 1.1 and taker <= 15.0 * 1.1
    )
    if ok:
        return 'OK'
    if warn:
        return 'WARN'
    return 'FAIL'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)

    edge = _read_json('artifacts/EDGE_REPORT.json') or {}
    total = edge.get('total', {})
    edge_net = _finite(total.get('net_bps', 0.0))
    # We do not have a global order_age_p95_ms in artifacts; reuse latency p95 if present
    metrics = _read_json('artifacts/metrics.json') or {}
    latency = _finite(((metrics.get('latency') or {}).get('p95_ms_avg', 0.0)))
    taker = _finite(((metrics.get('pnl') or {}).get('total_taker_share_pct', 0.0)))
    fill_rate = _finite(((metrics.get('pnl') or {}).get('total_fill_rate', 0.0)))
    pos_skew_abs_p95 = _finite(((metrics.get('position_skew') or {}).get('abs_p95', 0.0)))
    caps_breach_count = int(_finite(((metrics.get('intraday_caps') or {}).get('breach_count', 0.0))))

    rec_path = _find_latest_soak_reconcile()
    # region compare optional (unused in fields but triggers generation elsewhere)
    _ = _read_json('artifacts/REGION_COMPARE.json')

    verdict = _verdict(edge_net, latency, taker)

    # Regression guard (optional)
    try:
        from tools.soak.regression_guard import check as reg_check
        # read last 7 soak reports
        import glob
        paths = sorted(glob.glob('artifacts/REPORT_SOAK_*.json'))[-7:]
        last7 = []
        for p in paths:
            try:
                last7.append(_read_json(p) or {})
            except Exception:
                pass
        reg = reg_check({'edge_net_bps': edge_net, 'order_age_p95_ms': latency, 'taker_share_pct': taker}, last7)
    except Exception:
        reg = {'ok': True, 'reason': 'NONE', 'baseline': {'edge_med': 0.0, 'p95_med': 0.0, 'taker_med': 0.0}}

    report = {
        'alerts': {'critical': 0, 'warning': 0},
        'caps_breach_count': caps_breach_count,
        'edge_net_bps': edge_net,
        'fill_rate': fill_rate,
        'order_age_p95_ms': latency,
        'pos_skew_abs_p95': pos_skew_abs_p95,
        'reg_guard': {'reason': reg.get('reason', 'NONE'), 'baseline': reg.get('baseline', {})},
        'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'},
        'taker_share_pct': taker,
        'verdict': 'FAIL' if (verdict != 'FAIL' and not reg.get('ok', True)) else verdict,
    }

    # Optional: attach anomaly radar top-3 if day buckets available
    try:
        import subprocess
        import sys as _sys
        day_edge = 'artifacts/EDGE_REPORT_DAY.json'
        if Path(day_edge).exists():
            out_json = 'artifacts/ANOMALY_RADAR.json'
            subprocess.run([_sys.executable, '-m', 'tools.soak.anomaly_radar', '--edge-report', day_edge, '--bucket-min', '15', '--out-json', out_json], check=False)
            ar = _read_json(out_json) or {}
            anoms = list(ar.get('anomalies') or [])
            # keep only first 3
            report['diagnostics'] = {'anomalies': anoms[:3]}
    except Exception:
        pass

    _write_json_atomic(args.out, report)
    md_path = os.path.splitext(args.out)[0] + '.md'
    lines = []
    lines.append('SOAK DAILY REPORT\n')
    lines.append('\n')
    lines.append('| edge_net_bps | order_age_p95_ms | taker_share_pct | fill_rate | pos_skew_abs_p95 | caps_breach_count | verdict |\n')
    lines.append('|--------------|------------------|-----------------|-----------|------------------|-------------------|---------|\n')
    lines.append('| ' + '%.6f' % report['edge_net_bps'] + ' | ' + '%.6f' % report['order_age_p95_ms'] + ' | ' + '%.6f' % report['taker_share_pct'] + ' | ' + '%.6f' % report['fill_rate'] + ' | ' + '%.6f' % report['pos_skew_abs_p95'] + ' | ' + str(int(report['caps_breach_count'])) + ' | ' + report['verdict'] + ' |\n')
    _write_text_atomic(md_path, ''.join(lines))

    print('WROTE', args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



import argparse
import glob
import json
import os
from datetime import datetime, timezone


def _read(path: str):
    try:
        with open(path, 'r', encoding='ascii') as f:
            return json.load(f)
    except Exception:
        return None


def _latest(pattern: str):
    xs = sorted(glob.glob(pattern))
    return xs[-1] if xs else ''


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


def _date_from_report(rep: dict) -> str:
    try:
        utc = str(((rep.get('runtime') or {}).get('utc', '')))
        if utc and 'T' in utc:
            return utc.split('T')[0]
    except Exception:
        pass
    # Use frozen time if available for deterministic output
    iso_freeze = os.environ.get('MM_FREEZE_UTC_ISO')
    if iso_freeze:
        try:
            return datetime.strptime(iso_freeze, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
        except Exception:
            pass
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _float(x):
    try:
        import math
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except Exception:
        return 0.0


def _top_from_sentinel(s: dict):
    out = []
    try:
        top = (s.get('top') or {})
        syms = top.get('top_symbols_by_net_drop') or []
        if syms:
            out.append('Top symbols by net drop: ' + ','.join(syms))
        buckets = top.get('top_buckets_by_net_drop') or []
        if buckets:
            out.append('Top buckets by net drop: ' + ','.join(buckets))
    except Exception:
        pass
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--scope', choices=['day','week'], required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)

    lines = []

    if args.scope == 'day':
        drift = _read('artifacts/DRIFT_STOP.json') or {}
        reg = _read('artifacts/REG_GUARD_STOP.json') or {}
        soak_path = _latest('artifacts/REPORT_SOAK_*.json')
        soak = _read(soak_path) or {}
        sentinel = _read('artifacts/EDGE_SENTINEL.json') or {}

        day = _date_from_report(soak)
        lines.append(f'POSTMORTEM (DAY) {day}\n')
        lines.append('\n')
        lines.append('Outcome: FAIL\n')
        lines.append('\n')
        lines.append('Timeline:\n')
        if drift.get('reason'):
            lines.append('- Drift guard stop: reason=' + str(drift.get('reason')) + '\n')
        if reg.get('reason'):
            lines.append('- Regression guard stop: reason=' + str(reg.get('reason')) + '\n')
        if soak:
            lines.append('- Daily report verdict=' + str(soak.get('verdict','')) + '\n')
        for t in _top_from_sentinel(sentinel):
            lines.append('- Sentinel: ' + t + '\n')
        lines.append('\n')

        # Metrics
        lines.append('| net_bps | order_age_p95_ms | taker_share_pct | fill_rate |\n')
        lines.append('|---------|-------------------|-----------------|-----------|\n')
        lines.append('| ' + '%.6f' % _float(soak.get('edge_net_bps',0.0)) + ' | ' + '%.6f' % _float(soak.get('order_age_p95_ms',0.0)) + ' | ' + '%.6f' % _float(soak.get('taker_share_pct',0.0)) + ' | ' + '%.6f' % _float(soak.get('fill_rate',0.0)) + ' |\n')
        lines.append('\n')

        # Action items
        adv = []
        try:
            adv = list((sentinel.get('advice') or []) )[:3]
        except Exception:
            adv = []
        if adv:
            lines.append('Action items:\n')
            for a in adv:
                lines.append('- ' + str(a) + '\n')

    else:  # week
        wk = _read('artifacts/WEEKLY_ROLLUP.json') or {}
        gate = _read('artifacts/KPI_GATE.json') or {}
        p = wk.get('period') or {}
        lines.append('POSTMORTEM (WEEK) ' + str(p.get('from','')) + ' → ' + str(p.get('to','')) + '\n')
        lines.append('\n')
        lines.append('Outcome: ' + str(gate.get('verdict','')) + '\n')
        lines.append('\n')
        lines.append('| edge_med | p95_med | taker_med |\n')
        lines.append('|----------|---------|-----------|\n')
        lines.append('| ' + '%.6f' % _float((wk.get('edge_net_bps') or {}).get('median',0.0)) + ' | ' + '%.6f' % _float((wk.get('order_age_p95_ms') or {}).get('median',0.0)) + ' | ' + '%.6f' % _float((wk.get('taker_share_pct') or {}).get('median',0.0)) + ' |\n')
        lines.append('\n')
        if gate.get('reasons'):
            lines.append('Gate reasons: ' + ','.join(gate.get('reasons')) + '\n')

    md = ''.join(lines)
    _write_text_atomic(args.out, md)
    print('WROTE', args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



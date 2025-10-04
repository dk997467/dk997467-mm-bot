import argparse
import glob
import json
import os
from datetime import datetime, timezone, timedelta


def _read_json(path: str):
    try:
        with open(path, 'r', encoding='ascii') as f:
            return json.load(f)
    except Exception:
        return None


def _latest(path_glob: str):
    c = sorted(glob.glob(path_glob))
    return c[-1] if c else None


def _status_icon(verdict: str) -> str:
    if verdict == 'OK':
        return '[OK]'
    if verdict == 'WARN':
        return '[WARN]'
    return '[FAIL]'


def _now_utc_ts() -> int:
    iso = os.environ.get('MM_FREEZE_UTC_ISO')
    if iso:
        try:
            return int(datetime.strptime(iso, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            pass
    return int(datetime.now(timezone.utc).timestamp())


def _parse_iso_ts(s: str) -> int:
    try:
        return int(datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp())
    except Exception:
        return 0


def _emit_soak_summary(journal_path: str, hours: int) -> None:
    now_ts = _now_utc_ts()
    cutoff = now_ts - int(hours) * 3600
    cont = warn = fail = actions_total = 0
    last_ts = 0
    if not journal_path or not os.path.exists(journal_path):
        print('event=daily_digest_soak result=OK cont=0 warn=0 fail=0 actions=0 last_ts=0')
        return
    try:
        with open(journal_path, 'r', encoding='ascii') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts_s = str(rec.get('ts', ''))
                ts_i = _parse_iso_ts(ts_s)
                if ts_i < cutoff:
                    continue
                st = str(rec.get('status', ''))
                ac = str(rec.get('action', ''))
                if st == 'CONTINUE':
                    cont += 1
                elif st == 'WARN':
                    warn += 1
                elif st == 'FAIL':
                    fail += 1
                if ac:
                    actions_total += 1 if ac != 'NONE' else 0
                if ts_i > last_ts:
                    last_ts = ts_i
    except Exception:
        pass
    result = 'OK'
    if fail > 0:
        result = 'FAIL'
    elif warn > 0:
        result = 'ATTN'
    print(f'event=daily_digest_soak result={result} cont={cont} warn={warn} fail={fail} actions={actions_total} last_ts={last_ts}')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=False)
    ap.add_argument('--journal', required=False, default=None)
    ap.add_argument('--hours', type=int, default=24)
    args = ap.parse_args(argv)

    edge = _read_json('artifacts/EDGE_REPORT.json') or {}
    edge_total = edge.get('total', {}) if isinstance(edge, dict) else {}
    soak_path = _latest('artifacts/REPORT_SOAK_*.json')
    soak = _read_json(soak_path) or {}
    ledger = _read_json('artifacts/LEDGER_DAILY.json') or []
    drift = _read_json('artifacts/DRIFT_STOP.json') or {}
    reg = _read_json('artifacts/REG_GUARD_STOP.json') or {}
    sentinel = _read_json('artifacts/EDGE_SENTINEL.json') or {}

    # metrics
    net = float(edge_total.get('net_bps', 0.0))
    p95 = float(soak.get('order_age_p95_ms', 0.0))
    tak = float(soak.get('taker_share_pct', 0.0))
    fills = float(edge_total.get('fills', 0.0))
    turnover = float(edge_total.get('turnover_usd', 0.0))
    verdict = str(soak.get('verdict', 'OK'))

    # trend vs yesterday
    yesterday = None
    if soak_path:
        ylist = sorted(glob.glob('artifacts/REPORT_SOAK_*.json'))
        if len(ylist) >= 2:
            yesterday = _read_json(ylist[-2]) or {}
    trend = {}
    if yesterday:
        trend = {
            'edge_net_bps_delta': float(net - float(yesterday.get('edge_net_bps', 0.0))),
            'order_age_p95_ms_delta': float(p95 - float(yesterday.get('order_age_p95_ms', 0.0))),
            'taker_share_pct_delta': float(tak - float(yesterday.get('taker_share_pct', 0.0))),
        }

    # Advice from sentinel
    advice = []
    try:
        advice = list(sentinel.get('advice', []))[:3]
    except Exception:
        advice = []

    lines = []
    # Use frozen time if available for deterministic output
    iso_freeze = os.environ.get('MM_FREEZE_UTC_ISO')
    if iso_freeze:
        try:
            now = datetime.strptime(iso_freeze, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
        except Exception:
            now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    else:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    lines.append(f'DAILY DIGEST {now} { _status_icon(verdict) }\n')
    lines.append('\n')
    lines.append('| net_bps | order_age_p95_ms | taker_share_pct | fills | turnover_usd |\n')
    lines.append('|---------|-------------------|-----------------|-------|--------------|\n')
    lines.append('| ' + '%.6f' % net + ' | ' + '%.6f' % p95 + ' | ' + '%.6f' % tak + ' | ' + '%.6f' % fills + ' | ' + '%.6f' % turnover + ' |\n')
    lines.append('\n')
    if trend:
        lines.append('Trend vs yesterday:\n')
        lines.append('- edge_net_bps_delta: ' + '%.6f' % trend['edge_net_bps_delta'] + '\n')
        lines.append('- order_age_p95_ms_delta: ' + '%.6f' % trend['order_age_p95_ms_delta'] + '\n')
        lines.append('- taker_share_pct_delta: ' + '%.6f' % trend['taker_share_pct_delta'] + '\n')
        lines.append('\n')
    if drift.get('reason'):
        lines.append('Drift Guard: ' + drift.get('reason') + '\n')
    if reg.get('reason'):
        lines.append('Regression Guard: ' + reg.get('reason') + '\n')
    if advice:
        lines.append('\nActionables:\n')
        for a in advice:
            lines.append('- ' + a + '\n')

    md = ''.join(lines)
    # Ensure exactly one trailing newline
    md = md.rstrip('\n') + '\n'
    if args.out:
        # write
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        tmp = args.out + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(md)
            if not md.endswith('\n'):
                f.write('\n')
            f.flush(); os.fsync(f.fileno())
        if os.path.exists(args.out):
            os.replace(tmp, args.out)
        else:
            os.rename(tmp, args.out)
        print('WROTE', args.out)
        # NOTE: normalize_eol removed - line endings handled by .gitattributes and test normalization

    # optional soak summary
    if args.journal:
        _emit_soak_summary(args.journal, int(args.hours))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



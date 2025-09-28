import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

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
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def _read_yaml(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='ascii') as f:
        return yaml.safe_load(f)


def _now_iso() -> str:
    return os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z')


def _parse_iso_to_epoch(iso: str) -> float:
    try:
        # Accept YYYY-MM-DDTHH:MM:SSZ
        import datetime as _dt
        if iso.endswith('Z'):
            iso = iso[:-1]
        dt = _dt.datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_dt.timezone.utc).timestamp()
        return dt.timestamp()
    except Exception:
        return 0.0


def _last_journal_entry(path: str) -> Optional[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(path, 'rb') as f:
            # Read last non-empty line efficiently
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            buf = b''
            while pos > 0:
                step = min(1024, pos)
                pos -= step
                f.seek(pos)
                buf = f.read(step) + buf
                if b'\n' in buf:
                    break
            line = buf.splitlines()[-1] if buf else b''
        if not line:
            return None
        return json.loads(line.decode('ascii'))
    except Exception:
        return None


def _append_journal(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # De-duplicate if last entry matches ignoring 'utc'
    last = _last_journal_entry(path)
    obj_no_utc = {k: v for k, v in obj.items() if k != 'utc'}
    if last is not None:
        last_no_utc = {k: v for k, v in last.items() if k != 'utc'}
        if last_no_utc == obj_no_utc:
            return
    line = json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    with open(path, 'a', encoding='ascii', newline='') as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--regions', required=True)
    ap.add_argument('--compare', required=True)
    ap.add_argument('--current', required=True)
    ap.add_argument('--window', default='')
    ap.add_argument('--cooldown-file', required=True)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)

    cfg = _read_yaml(args.regions)
    comp = _read_json(args.compare) or {}

    winner = (comp.get('winner') or {})
    win_region = str(winner.get('region') or '')
    win_window = str(winner.get('window') or '')
    windows = (comp.get('windows') or {})
    m = (windows.get(win_window) or {})

    regions = cfg.get('regions', [])
    switch = cfg.get('switch', {})
    safe = (switch.get('safe_thresholds') or {})
    cooldown_s = int(_finite(switch.get('cooldown_s', 0)))

    # Lookup region enabled
    enabled = False
    for r in regions:
        if str(r.get('name')) == win_region and r.get('enabled') is True:
            enabled = True
            break

    checks = {
        'enabled': enabled,
        'net_bps_min': _finite(m.get('net_bps', 0.0)) >= _finite(safe.get('net_bps_min', 0.0)),
        'order_age_p95_ms_max': _finite(m.get('order_age_p95_ms', 1e18)) <= _finite(safe.get('order_age_p95_ms_max', 1e18)),
        'taker_share_pct_max': _finite(m.get('taker_share_pct', 1e18)) <= _finite(safe.get('taker_share_pct_max', 1e18)),
        'window_match': True if not args.window else (win_window == args.window),
        'cooldown_ok': True,
    }

    # Cooldown check
    last_switch_utc = ''
    cdata = _read_json(args.cooldown_file)
    if cdata and 'last_switch_utc' in cdata:
        last_switch_utc = str(cdata.get('last_switch_utc') or '')
    if last_switch_utc:
        now_ts = time.time()
        last_ts = _parse_iso_to_epoch(last_switch_utc)
        checks['cooldown_ok'] = (now_ts - last_ts) >= float(cooldown_s)

    reason = 'better_net_bps_tie_latency'
    plan = {
        'checks': checks,
        'from': args.current,
        'reason': reason,
        'runtime': {'utc': _now_iso(), 'version': '0.1.0'},
        'to': win_region,
        'window': win_window,
    }

    # Print deterministic ASCII plan as JSON
    print(json.dumps(plan, ensure_ascii=True, sort_keys=True, separators=(",", ":")))

    ok = all(checks.values())
    if args.apply and ok:
        # Append journal
        jline = {
            'checks': checks,
            'from': args.current,
            'reason': reason,
            'to': win_region,
            'utc': _now_iso(),
            'window': win_window,
        }
        _append_journal('tools/region/rollout_journal.jsonl', jline)
        # Update cooldown
        _write_json_atomic(args.cooldown_file, {'last_switch_utc': _now_iso()})

    return 0


if __name__ == '__main__':
    raise SystemExit(main())



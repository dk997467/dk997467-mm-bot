import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _read_json(path: str):
    with open(path, 'r', encoding='ascii') as f:
        return json.load(f)


essential_safe = {
    'net_bps_min': 2.50,
    'order_age_p95_ms_max': 350,
    'taker_share_pct_max': 15,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--current', required=True)
    ap.add_argument('--compare', required=True)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)

    rep = _read_json(args.compare)
    w = rep.get('winner', {})
    region = w.get('region', '')
    window = w.get('window', '')

    if not region:
        print('no winner: staying on current', file=sys.stdout)
        return 0

    m = rep.get('windows', {}).get(window, {})
    ok = (
        float(m.get('net_bps', 0.0)) >= essential_safe['net_bps_min'] and
        float(m.get('order_age_p95_ms', 1e18)) <= essential_safe['order_age_p95_ms_max'] and
        float(m.get('taker_share_pct', 1e18)) <= essential_safe['taker_share_pct_max']
    )

    eta = 'immediate' if ok else 'blocked(cooldown)'
    plan = f"from={args.current} to={region} window={window} reason=better_net_bps eta={eta}"
    print(plan, file=sys.stdout)

    if not args.apply:
        return 0

    # Real switch is a no-op for now
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

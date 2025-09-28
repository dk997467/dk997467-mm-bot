import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d')


def _exists(path: str) -> bool:
    return os.path.exists(path)


def _run(cmd, env=None) -> int:
    r = subprocess.run(cmd, text=True, capture_output=True, env=env)
    return r.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=8)
    ap.add_argument('--mode', default='shadow')
    ap.add_argument('--econ', choices=['yes', 'no'], default='yes')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    # Plan
    print('SOAK AUTOPILOT PLAN')
    print(' - mode=', args.mode)
    print(' - hours=', args.hours)
    print(' - econ_profile=', args.econ)
    print(' - dry_run=', bool(args.dry_run))

    if args.dry_run:
        print('AUTOPILOT=OK')
        return 0

    env = os.environ.copy()
    if args.econ == 'yes':
        env['MM_PROFILE'] = 'econ_moderate'

    ok = True

    # Step 1: runner
    rc = _run([sys.executable, '-m', 'tools.soak.runner', '--mode', args.mode, '--hours', str(args.hours)], env)
    print(('[OK] ' if rc == 0 else '[FAIL] ') + 'runner')
    ok = ok and (rc == 0)

    # Step 2: virtual balance (if fixtures found)
    trades = 'tests/fixtures/ledger/trades_case1.jsonl'
    prices = 'tests/fixtures/ledger/prices_case1.jsonl'
    if _exists(trades) and _exists(prices):
        rc = _run([sys.executable, '-m', 'tools.sim.virtual_balance', '--trades', trades, '--prices', prices], env)
        print(('[OK] ' if rc == 0 else '[FAIL] ') + 'virtual_balance')
        ok = ok and (rc == 0)
    else:
        print('[WARN] virtual_balance fixtures missing')

    # Step 3: daily report
    out = f'artifacts/REPORT_SOAK_{_utc_date()}.json'
    rc = _run([sys.executable, '-m', 'tools.soak.daily_report', '--out', out], env)
    print(('[OK] ' if rc == 0 else '[FAIL] ') + 'daily_report')
    ok = ok and (rc == 0)

    print('AUTOPILOT=' + ('OK' if ok else 'FAIL'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



import argparse
import datetime as dt
import os


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--weeks', type=int, default=2)
    ap.add_argument('--hours-per-night', type=int, default=8)
    ap.add_argument('--econ', choices=['yes','no'], default='yes')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    weeks = max(1, args.weeks)
    start = dt.date(1970,1,1)
    lines = []
    lines.append('LONG SOAK PLAN\n')
    for w in range(weeks):
        for d in range(7):
            day = start + dt.timedelta(days=w*7+d)
            dow = day.weekday()  # 0=Mon .. 6=Sun
            lines.append(f'{day.isoformat()} nightly: sh tools/soak/nightly.sh (hours={args.hours_per_night}, econ={args.econ})\n')
            lines.append(f'{day.isoformat()} after: python -m tools.ops.daily_check; python -m tools.ops.daily_digest --out artifacts/DAILY_DIGEST.md; python -m tools.ops.rotate_artifacts --roots artifacts dist --keep-days 14 --max-size-gb 2.0 --archive-dir dist/archives\n')
            if dow == 5:  # Saturday
                lines.append(f'{day.isoformat()} weekly: python -m tools.soak.weekly_rollup --soak-dir artifacts --ledger artifacts/LEDGER_DAILY.json --out-json artifacts/WEEKLY_ROLLUP.json --out-md artifacts/WEEKLY_ROLLUP.md\n')
                lines.append(f'{day.isoformat()} gate: python -m tools.soak.kpi_gate\n')

    plan = ''.join(lines)
    print(plan, end='')
    print('LONG_SOAK_PLAN=' + ('READY' if args.dry_run else 'DONE'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



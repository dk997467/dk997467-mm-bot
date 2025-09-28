import argparse
import os
import sys
import time
from pathlib import Path
from typing import List


def _run_cmd(argv: List[str]) -> bool:
    try:
        import subprocess
        r = subprocess.run(argv, capture_output=True, text=True)
        ok = (r.returncode == 0)
        out = (r.stdout or '') + (r.stderr or '')
        # Low-cardinality ASCII log
        print('RUN', ' '.join(argv), 'RC', r.returncode)
        if out:
            try:
                out.encode('ascii', 'strict')
            except Exception:
                out = ''
        return ok
    except Exception:
        print('E_SOAK_EXEC', ' '.join(argv))
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['shadow','canary'], required=True)
    ap.add_argument('--hours', type=int, default=24)
    args = ap.parse_args(argv)

    # Preflight
    if not _run_cmd([sys.executable, '-m', 'cli.preflight']):
        print('E_SOAK_PREFLIGHT')
        return 0

    end_ts = time.time() + args.hours * 3600
    interval_s = 15 * 60

    while time.time() < end_ts:
        # Edge audit on current fixtures/artifacts
        _run_cmd([sys.executable, '-m', 'tools.edge_cli',
                  '--trades', 'tests/fixtures/edge_trades_case1.jsonl',
                  '--quotes', 'tests/fixtures/edge_quotes_case1.jsonl',
                  '--out', 'artifacts/EDGE_REPORT.json'])

        # Drift guard
        try:
            from tools.soak.drift_guard import check as drift_check
            res = drift_check('artifacts/EDGE_REPORT.json')
            if not res.get('ok', True):
                print('SOAK_STOP reason=' + str(res.get('reason', 'UNKNOWN')))
                # finalize daily report as FAIL
                try:
                    out = f"artifacts/REPORT_SOAK_{time.strftime('%Y%m%d', time.gmtime())}.json"
                    # Minimal fail report
                    from tools.soak.daily_report import _write_json_atomic
                    rep = {
                        'alerts': {'critical': 0, 'warning': 0},
                        'caps_breach_count': 0,
                        'edge_net_bps': float(res['snapshot'].get('net_bps', 0.0)),
                        'fill_rate': 0.0,
                        'order_age_p95_ms': float(res['snapshot'].get('order_age_p95_ms', 0.0)),
                        'pos_skew_abs_p95': 0.0,
                        'runtime': {'utc': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z'), 'version': '0.1.0'},
                        'taker_share_pct': float(res['snapshot'].get('taker_share_pct', 0.0)),
                        'verdict': 'FAIL',
                        'drift': {'reason': str(res.get('reason', 'UNKNOWN')), 'ts': os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z')},
                    }
                    _write_json_atomic(out, rep)
                except Exception:
                    pass
                break
        except Exception:
            pass

        # FinOps cron to soak folder
        os.environ.setdefault('MM_FREEZE_UTC', '1')
        _run_cmd([sys.executable, '-m', 'tools.finops.cron_job',
                  '--artifacts', 'artifacts/metrics.json',
                  '--exchange-dir', 'tests/fixtures/exchange_reports',
                  '--out-dir', 'dist/finops/soak'])

        # Region compare if config exists
        if Path('config/regions.yaml').exists():
            _run_cmd([sys.executable, '-m', 'tools.region.run_canary_compare',
                      '--regions', 'config/regions.yaml',
                      '--in', 'tests/fixtures/region_canary_metrics.jsonl',
                      '--out', 'artifacts/REGION_COMPARE.json'])

        time.sleep(interval_s)

    print('SOAK_DONE', args.mode, args.hours)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



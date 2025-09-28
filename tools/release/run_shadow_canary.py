import os
import sys
from pathlib import Path


def _check_file_exists(path: str, desc: str) -> bool:
    if Path(path).exists():
        print(f'[OK] {desc}: {path}')
        return True
    else:
        print(f'[MISSING] {desc}: {path}')
        return False


def main() -> int:
    print('Shadow→Canary→Live Release Plan')
    print('===============================')
    print()
    
    print('PHASE 1: SHADOW (30-60 min)')
    print('- Enable metrics/logs collection')
    print('- NO live orders, observation only')
    print('- Monitor: latency, fills, edge components')
    print()
    
    print('PHASE 2: CANARY (2-4 hours)')
    print('- Route 5-10% of volume')
    print('- Full order lifecycle active')
    print('- GO/NO-GO thresholds enforced')
    print()
    
    print('PHASE 3: PROMOTE/ROLLBACK')
    print('- If GO: gradual ramp to 100%')
    print('- If NO-GO: immediate rollback to previous')
    print('- Alert channels: #trading-alerts, PagerDuty')
    print()
    
    print('Readiness Check:')
    print('================')
    
    all_ok = True
    
    # Check key utilities
    checks = [
        ('cli/preflight.py', 'Preflight checker'),
        ('tools/finops/exporter.py', 'FinOps exporter'),
        ('tools/edge_cli.py', 'Edge audit CLI'),
        ('src/sim/run_sim.py', 'Live sim runner'),
        ('tools/backtest/cli.py', 'Backtest CLI'),
        ('tools/region/run_canary_compare.py', 'Region compare'),
        ('tools/finops/cron_job.py', 'FinOps cron'),
        ('tools/release/go_nogo.py', 'GO/NO-GO checker'),
    ]
    
    for path, desc in checks:
        if not _check_file_exists(path, desc):
            all_ok = False
    
    print()
    if all_ok:
        print('[READY] All components available')
        print('Next: run shadow phase with monitoring')
    else:
        print('[NOT READY] Missing components detected')
        print('Fix missing files before proceeding')
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

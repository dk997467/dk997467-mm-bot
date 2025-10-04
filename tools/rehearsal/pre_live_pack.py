import json
import os
import subprocess
import sys
from typing import Any, Dict, List

from src.common.artifacts import write_json_atomic


def _run(cmd: List[str]) -> Dict[str, Any]:
    try:
        # Add 5 minute timeout to prevent hanging subprocesses
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out = (r.stdout or '').strip().splitlines()
        err = (r.stderr or '').strip().splitlines()
        tail = ''
        for lines in (out[::-1], err[::-1]):
            for ln in lines:
                if ln:
                    tail = ln
                    break
            if tail:
                break
        return {'code': int(r.returncode), 'tail': tail}
    except subprocess.TimeoutExpired:
        return {'code': 124, 'tail': 'TIMEOUT: Command exceeded 5 minutes'}
    except Exception as e:
        return {'code': 99, 'tail': f'EXC:{e.__class__.__name__}'}


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    # Delegate to shared, battle-tested implementation
    write_json_atomic(path, data)


def main(argv=None) -> int:
    # Fixed UTC for determinism unless provided
    utc = os.environ.get('MM_FREEZE_UTC_ISO', '1970-01-01T00:00:00Z')

    steps: List[Dict[str, Any]] = []

    # 1) bug bash
    if os.environ.get('PRE_LIVE_SKIP_BUG_BASH', '0') == '1':
        steps.append({'name': 'bug_bash', 'ok': True, 'details': 'skipped'})
    else:
        r = _run([sys.executable, 'tools/ci/run_bug_bash.py'])
        steps.append({'name': 'bug_bash', 'ok': r['code'] == 0 and 'RESULT=OK' in r.get('tail',''), 'details': r.get('tail','')})

    # 2) soak.autopilot dry-run
    r = _run([sys.executable, '-m', 'tools.soak.autopilot', '--hours', '1', '--mode', 'shadow', '--econ', 'yes', '--dry-run'])
    steps.append({'name': 'autopilot_dry', 'ok': r['code'] == 0 and 'AUTOPILOT=OK' in r.get('tail',''), 'details': r.get('tail','')})

    # 3) ops.daily_check (tolerant to missing files)
    r = _run([sys.executable, '-m', 'tools.ops.daily_check'])
    steps.append({'name': 'daily_check', 'ok': r['code'] == 0 and 'RESULT=OK' in r.get('tail',''), 'details': r.get('tail','')})

    # 4) edge_sentinel on fixtures
    r = _run([sys.executable, '-m', 'tools.edge_sentinel.analyze', '--trades', 'tests/fixtures/edge_sentinel/trades.jsonl', '--quotes', 'tests/fixtures/edge_sentinel/quotes.jsonl', '--out-json', 'artifacts/EDGE_SENTINEL.json'])
    ok_sentinel = r['code'] == 0
    steps.append({'name': 'edge_sentinel', 'ok': ok_sentinel, 'details': r.get('tail','')})
    if ok_sentinel:
        _run([sys.executable, '-m', 'tools.edge_sentinel.report', 'artifacts/EDGE_SENTINEL.json'])

    # 5) sweep.run_sweep on fixtures
    r = _run([sys.executable, '-m', 'tools.sweep.run_sweep', '--events', 'tests/fixtures/sweep/events_case1.jsonl', '--grid', 'tools/sweep/grid.yaml', '--out-json', 'artifacts/PARAM_SWEEP.json'])
    steps.append({'name': 'param_sweep', 'ok': r['code'] == 0, 'details': r.get('tail','')})

    # 6) tuning.apply_from_sweep (dry profile overlay)
    r = _run([sys.executable, '-m', 'tools.tuning.apply_from_sweep'])
    steps.append({'name': 'apply_from_sweep', 'ok': r['code'] == 0, 'details': r.get('tail','')})

    # 7) chaos.soak_failover --dry-run
    r = _run([sys.executable, '-m', 'tools.chaos.soak_failover', '--dry-run'])
    steps.append({'name': 'chaos_failover_dry', 'ok': r['code'] == 0, 'details': r.get('tail','')})

    # 8) ops.rotate_artifacts --dry-run
    r = _run([sys.executable, '-m', 'tools.ops.rotate_artifacts', '--roots', 'artifacts', 'dist', '--keep-days', '14', '--max-size-gb', '1.0', '--archive-dir', 'dist/archives', '--dry-run'])
    steps.append({'name': 'rotate_artifacts_dry', 'ok': r['code'] == 0, 'details': r.get('tail','')})

    # 9) scan_secrets
    r = _run([sys.executable, '-m', 'tools.ci.scan_secrets'])
    steps.append({'name': 'scan_secrets', 'ok': r['code'] == 0, 'details': r.get('tail','')})

    result_ok = all(s.get('ok') for s in steps)
    pack = {
        'result': 'OK' if result_ok else 'FAIL',
        'runtime': {'utc': utc, 'version': '0.1.0'},
        'steps': steps,
    }
    _write_json_atomic('artifacts/PRE_LIVE_PACK.json', pack)
    print('PRE_LIVE_PACK', pack['result'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



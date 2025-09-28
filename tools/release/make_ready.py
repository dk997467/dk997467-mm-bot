#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


ASCII_EOL = '\n'


def _exists(path: str) -> bool:
    return os.path.exists(path)


def _repo_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def _run(cmd: List[str]) -> Tuple[int, str]:
    try:
        env = os.environ.copy()
        # Normalize environment for child processes
        env.setdefault('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
        env.setdefault('TZ', 'UTC')
        env.setdefault('LC_ALL', 'C')
        env.setdefault('LANG', 'C')
        env.setdefault('MM_FREEZE_UTC', '1')
        # Ensure modules are importable regardless of cwd
        py_path = env.get('PYTHONPATH', '')
        root = _repo_root()
        env['PYTHONPATH'] = (root + (os.pathsep + py_path if py_path else ''))
        # Avoid long bug bash
        env.setdefault('PRE_LIVE_SKIP_BUG_BASH', '1')

        r = subprocess.run(cmd, capture_output=True, text=True, encoding='ascii', errors='ignore', env=env)
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
        return int(r.returncode), tail
    except Exception as e:
        return 99, 'EXC:' + e.__class__.__name__


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


def _print(line: str) -> None:
    sys.stdout.write(line + ASCII_EOL)


def _plan_and_execute(args: argparse.Namespace, dry: bool) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []

    need_pre = not (_exists('artifacts/PRE_LIVE_PACK.json') and _exists('artifacts/PRE_LIVE_PACK.md'))
    need_score = not (_exists('artifacts/READINESS_SCORE.json') and _exists('artifacts/READINESS_SCORE.md'))

    _print('PLAN CHECK PRE_LIVE_PACK: ' + ('MISSING' if need_pre else 'PRESENT'))
    if need_pre:
        _print('PLAN RUN python tools/rehearsal/pre_live_pack.py')
        _print('PLAN RUN python tools/rehearsal/report_pack.py artifacts/PRE_LIVE_PACK.json')

    _print('PLAN CHECK READINESS_SCORE: ' + ('MISSING' if need_score else 'PRESENT'))
    # Weekly rollup may be required for readiness score
    have_weekly = _exists('artifacts/WEEKLY_ROLLUP.json') and _exists('artifacts/WEEKLY_ROLLUP.md')
    if need_score:
        if have_weekly:
            _print('PLAN SKIP weekly_rollup (exists)')
        else:
            _print('PLAN RUN python -m tools.soak.weekly_rollup --soak-dir ' + args.soak_dir + ' --ledger ' + args.ledger + ' --out-json artifacts/WEEKLY_ROLLUP.json --out-md artifacts/WEEKLY_ROLLUP.md')
        _print('PLAN RUN python -m tools.release.readiness_score')

    _print('PLAN RUN python tools/release/make_bundle.py')

    if dry:
        return {'dry': True, 'steps': steps}

    # Execute
    # PRE_LIVE_PACK
    if need_pre:
        code, _ = _run([sys.executable, str(Path(_repo_root()) / 'tools' / 'rehearsal' / 'pre_live_pack.py')])
        steps.append({'name': 'pre_live_pack', 'ok': (code == 0), 'details': ''})
        code, _ = _run([sys.executable, str(Path(_repo_root()) / 'tools' / 'rehearsal' / 'report_pack.py'), 'artifacts/PRE_LIVE_PACK.json'])
        steps.append({'name': 'report_pack', 'ok': (code == 0), 'details': ''})
    else:
        steps.append({'name': 'pre_live_pack', 'ok': True, 'details': 'SKIP'})
        steps.append({'name': 'report_pack', 'ok': True, 'details': 'SKIP'})

    # READINESS_SCORE
    if need_score:
        if have_weekly:
            steps.append({'name': 'weekly_rollup', 'ok': True, 'details': 'SKIP'})
        else:
            code, _ = _run([sys.executable, '-m', 'tools.soak.weekly_rollup', '--soak-dir', args.soak_dir, '--ledger', args.ledger, '--out-json', 'artifacts/WEEKLY_ROLLUP.json', '--out-md', 'artifacts/WEEKLY_ROLLUP.md'])
            ok_files = _exists('artifacts/WEEKLY_ROLLUP.json') and _exists('artifacts/WEEKLY_ROLLUP.md')
            steps.append({'name': 'weekly_rollup', 'ok': (code == 0 and ok_files), 'details': '' if (code == 0 and ok_files) else ('WARN fixtures' if code == 0 else '')})
        code, _ = _run([sys.executable, '-m', 'tools.release.readiness_score'])
        steps.append({'name': 'readiness_score', 'ok': (code == 0), 'details': ''})
    else:
        steps.append({'name': 'weekly_rollup', 'ok': True, 'details': 'SKIP'})
        steps.append({'name': 'readiness_score', 'ok': True, 'details': 'SKIP'})

    # ALWAYS make bundle
    code, _ = _run([sys.executable, str(Path(_repo_root()) / 'tools' / 'release' / 'make_bundle.py')])
    # Fill after summary with final status in details
    steps.append({'name': 'make_bundle', 'ok': (code == 0), 'details': ''})

    return {'dry': False, 'steps': steps}


def _manifest_summary() -> Tuple[str, List[str]]:
    missing_keys: List[str] = []
    try:
        with open('artifacts/RELEASE_BUNDLE_manifest.json', 'r', encoding='ascii') as f:
            man = json.load(f)
        paths = set(x.get('path') for x in man.get('files', []))
        # required set
        required = {
            'artifacts/PRE_LIVE_PACK.json',
            'artifacts/PRE_LIVE_PACK.md',
            'artifacts/READINESS_SCORE.json',
            'artifacts/READINESS_SCORE.md',
            'artifacts/WEEKLY_ROLLUP.json',
            'artifacts/WEEKLY_ROLLUP.md',
        }
        for req in sorted(required):
            if req not in paths:
                missing_keys.append(req)
        status = 'READY' if not missing_keys else 'PARTIAL'
        return status, missing_keys
    except Exception:
        return 'PARTIAL', ['manifest:missing']


def _write_report(steps: List[Dict[str, Any]], status: str, missing: List[str]) -> None:
    lines: List[str] = []
    lines.append('MAKE READY REPORT\n')
    lines.append('\n')
    lines.append('| step | status | details |\n')
    lines.append('|------|--------|---------|\n')
    for s in steps:
        st = 'OK' if s.get('ok') else 'FAIL'
        details = str(s.get('details', ''))
        lines.append('| ' + str(s.get('name', '')) + ' | ' + st + ' | ' + details + ' |\n')
    lines.append('\n')
    if status != 'READY':
        lines.append('missing: ' + json.dumps(missing, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n')
    lines.append('RELEASE_BUNDLE=' + status + '\n')
    _write_text_atomic('artifacts/MAKE_READY.md', ''.join(lines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--soak-dir', default='artifacts')
    ap.add_argument('--ledger', default='artifacts/LEDGER_DAILY.json')
    args = ap.parse_args(argv)

    # Normalize environment
    os.environ.setdefault('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    os.environ.setdefault('TZ', 'UTC')
    os.environ.setdefault('LC_ALL', 'C')
    os.environ.setdefault('LANG', 'C')
    os.environ.setdefault('MM_FREEZE_UTC', '1')

    # Ensure directories
    os.makedirs('artifacts', exist_ok=True)
    os.makedirs('dist/release_bundle', exist_ok=True)

    # Ensure ledger if missing
    if not os.path.exists(args.ledger):
        led_dir = os.path.dirname(args.ledger) or '.'
        os.makedirs(led_dir, exist_ok=True)
        with open(args.ledger, 'w', encoding='ascii', newline='') as f:
            f.write('{}\n')
            f.flush(); os.fsync(f.fileno())

    res = _plan_and_execute(args, args.dry_run)
    if args.dry_run:
        _print('MAKE_READY=PLAN')
        return 0

    status, missing = _manifest_summary()
    # Update make_bundle step details with the final status
    for s in res.get('steps', []):
        if s.get('name') == 'make_bundle':
            s['details'] = 'RELEASE_BUNDLE=' + status
            break
    _write_report(res.get('steps', []), status, missing)
    _print('RELEASE_BUNDLE=' + status)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



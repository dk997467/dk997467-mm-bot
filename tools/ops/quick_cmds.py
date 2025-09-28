#!/usr/bin/env python3
"""
Quick operator commands (stdlib-only, ASCII, deterministic plan, LF endings, atomic writes).

CLI:
  --do ready-bundle | full-validate | soak-14d | all
  --dry-run

Behavior:
  - Normalizes env: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, TZ=UTC, LANG=LC_ALL=C, MM_FREEZE_UTC=1 (if not set)
  - ready-bundle: python tools/release/make_ready.py; python tools/release/make_bundle.py
  - full-validate: python tools/ci/full_stack_validate.py; python tools/ci/report_full_stack.py artifacts/FULL_STACK_VALIDATION.json
  - soak-14d: python tools/soak/long_run.py --weeks 2 --hours-per-night 8 --econ yes
  - all: ready-bundle -> full-validate -> soak-14d

Dry-run prints deterministic plan lines and ends with QUICK_CMDS=PLAN (LF).
Real run writes artifacts/QUICK_CMDS_SUMMARY.md and ends with QUICK_CMDS=DONE.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


ASCII_EOL = "\n"


def _normalize_env(env: Dict[str, str]) -> Dict[str, str]:
    e = dict(env)
    e.setdefault('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    e.setdefault('TZ', 'UTC')
    e.setdefault('LC_ALL', 'C')
    e.setdefault('LANG', 'C')
    e.setdefault('MM_FREEZE_UTC', '1')
    return e


def _utc_iso() -> str:
    return os.environ.get('MM_FREEZE_UTC_ISO') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


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


def _run(cmd: List[str]) -> Tuple[int, str]:
    try:
        env = _normalize_env(os.environ.copy())
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


def _print(line: str) -> None:
    sys.stdout.write(line + ASCII_EOL)


def _steps_for(mode: str) -> List[List[str]]:
    steps: List[List[str]] = []
    if mode in ('ready-bundle', 'all'):
        steps.append([sys.executable, 'tools/release/make_ready.py'])
        steps.append([sys.executable, 'tools/release/make_bundle.py'])
    if mode in ('full-validate', 'all'):
        steps.append([sys.executable, 'tools/ci/full_stack_validate.py'])
        steps.append([sys.executable, 'tools/ci/report_full_stack.py', 'artifacts/FULL_STACK_VALIDATION.json'])
    if mode in ('soak-14d', 'all'):
        steps.append([sys.executable, 'tools/soak/long_run.py', '--weeks', '2', '--hours-per-night', '8', '--econ', 'yes'])
    return steps


def _format_cmd_line(cmd: List[str]) -> str:
    # For plan output, we want stable Python exe name
    disp = cmd[:]
    if disp and disp[0].endswith('python.exe'):
        disp[0] = 'python'
    elif disp and disp[0].endswith('python'):
        disp[0] = 'python'
    return 'RUN ' + ' '.join(disp)


def _write_summary(steps: List[Dict[str, Any]], utc: str, result: str) -> None:
    lines: List[str] = []
    lines.append('QUICK CMDS SUMMARY\n')
    lines.append('\n')
    lines.append('UTC: ' + utc + '\n')
    lines.append('\n')
    lines.append('| step | status | details |\n')
    lines.append('|------|--------|---------|\n')
    for s in steps:
        st = '✓' if s.get('ok') else '✗'
        details = str(s.get('details', ''))
        lines.append('| ' + str(s.get('name', '')) + ' | ' + st + ' | ' + details + ' |\n')
    lines.append('\n')
    lines.append('RESULT=' + result + '\n')
    _write_text_atomic('artifacts/QUICK_CMDS_SUMMARY.md', ''.join(lines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--do', required=True, choices=['ready-bundle', 'full-validate', 'soak-14d', 'all'])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    os.environ.setdefault('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    os.environ.setdefault('TZ', 'UTC')
    os.environ.setdefault('LC_ALL', 'C')
    os.environ.setdefault('LANG', 'C')
    os.environ.setdefault('MM_FREEZE_UTC', '1')

    steps = _steps_for(args.do)

    if args.dry_run:
        _print('QUICK CMDS PLAN')
        for cmd in steps:
            _print(_format_cmd_line(cmd))
        _print('QUICK_CMDS=PLAN')
        return 0

    # Real run
    exec_steps: List[Dict[str, Any]] = []
    ok_all = True
    for cmd in steps:
        code, tail = _run(cmd)
        ok = (code == 0)
        if not ok:
            ok_all = False
        exec_steps.append({'name': ' '.join(cmd[1:2] or cmd), 'ok': ok, 'details': tail})

    result = 'OK' if ok_all else 'FAIL'
    try:
        _write_summary(exec_steps, _utc_iso(), result)
    except Exception:
        # still continue to print DONE
        pass

    _print('QUICK_CMDS=DONE')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



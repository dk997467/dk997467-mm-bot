#!/usr/bin/env python3
"""
Validate alertmanager routing/inhibition and Prometheus rules runbook labels (stdlib-only).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
import argparse


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return ''


def validate_alertmanager(content: str) -> list[str]:
    errs = []
    # group_by includes alertname,strategy,env
    if not re.search(r"group_by:\s*\[\s*'alertname'\s*,\s*'strategy'\s*,\s*'env'\s*\]", content):
        errs.append('route_group_by')
    # group_wait, group_interval, repeat_interval present
    if 'group_wait: 30s' not in content:
        errs.append('route_group_wait')
    if 'group_interval: 5m' not in content:
        errs.append('route_group_interval')
    if 'repeat_interval: 4h' not in content:
        errs.append('route_repeat_interval')
    # inhibition rules CircuitTripped -> HighErrorRate and FullStackFail -> ComponentWarn
    if 'source_matchers: [ \'alertname = CircuitTripped\' ]' not in content or 'target_matchers: [ \'alertname = HighErrorRate\' ]' not in content:
        errs.append('inhibit_circuit_higherr')
    if 'source_matchers: [ \'alertname = FullStackFail\' ]' not in content or 'target_matchers: [ \'alertname = ComponentWarn\' ]' not in content:
        errs.append('inhibit_full_component')
    return errs


def validate_rules(content: str) -> list[str]:
    errs = []
    # each alert rule must contain severity and runbook_url (labels/annotations blocks)
    # naive split by '- alert:' blocks
    blocks = re.split(r"\n\s*- alert:\s*", content)
    for b in blocks[1:]:
        blk = '- alert: ' + b
        name_m = re.match(r"- alert:\s*(\S+)", blk)
        name = name_m.group(1) if name_m else 'UNKNOWN'
        # severity in labels
        if re.search(r"labels:\s*[\s\S]*?severity:\s*\"?(info|warning|critical)\"?", blk) is None:
            errs.append(f'severity_missing:{name}')
        # env present in labels
        if 'env:' not in blk and 'env =' not in blk:
            errs.append(f'env_missing:{name}')
        # runbook_url present in annotations
        if re.search(r"annotations:\s*[\s\S]*?runbook_url:\s*\S+", blk) is None:
            errs.append(f'runbook_missing:{name}')
    return errs


def validate_runbooks(root: Path) -> list[str]:
    errs = []
    for rel in (Path('docs/runbooks/circuit_gate.md'), Path('docs/runbooks/full_stack.md'), Path('docs/runbooks/kpi.md')):
        p = root / rel
        s = _read(p)
        if not s or not re.search(r"^#\s+", s):
            errs.append(f'runbook_h1_missing:{rel}')
    return errs


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--root', default='.')
    try:
        args, _ = ap.parse_known_args(argv)
    except SystemExit:
        args = ap.parse_args([])
    root = Path(args.root)
    am = _read(root / 'monitoring' / 'alertmanager.yml')
    rules = _read(root / 'monitoring' / 'alerts' / 'mm_bot.rules.yml')
    errs = []
    errs += validate_alertmanager(am)
    errs += validate_rules(rules)
    errs += validate_runbooks(root)
    status = 'OK' if not errs else 'FAIL'
    print(f"event=alerts_validate status={status} errors={len(errs)}")
    if errs:
        for e in errs:
            print(f"error={e}")
    return 0 if not errs else 1


if __name__ == '__main__':
    raise SystemExit(main())



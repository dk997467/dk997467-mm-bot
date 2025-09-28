#!/usr/bin/env python3
"""
Smoke-check repository tree for presence and basic sanity of key files.

Checks (best-effort):
- docs/INDEX.md exists and contains at least one H1 (# ...)
- monitoring/alerts/mm_bot.rules.yml is readable YAML-like (each non-empty non-comment line has a colon)
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List


def _ok_docs_index(root: Path) -> bool:
    p = root / 'docs' / 'INDEX.md'
    try:
        s = p.read_text(encoding='utf-8')
    except Exception:
        return False
    for line in s.splitlines():
        if line.strip().startswith('# '):
            return True
    return False


def _ok_alerts_yaml(root: Path) -> bool:
    p = root / 'monitoring' / 'alerts' / 'mm_bot.rules.yml'
    try:
        s = p.read_text(encoding='utf-8')
    except Exception:
        return False
    ok = True
    for ln in s.splitlines():
        t = ln.strip()
        if not t or t.startswith('#'):
            continue
        # very loose sanity: yml key-value lines include ':'
        if (':' not in t) and (not t.startswith('- ')):
            ok = False
            break
    return ok


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.')
    args = parser.parse_args(argv)
    root = Path(args.root)

    failures = []
    if not _ok_docs_index(root):
        failures.append('[FAIL] docs/INDEX.md missing or no H1')
    if not _ok_alerts_yaml(root):
        failures.append('[FAIL] mm_bot.rules.yml sanity')

    if failures:
        for f in failures:
            print(f)
        print('SMOKE=FAIL')
        return 1
    print('SMOKE=OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



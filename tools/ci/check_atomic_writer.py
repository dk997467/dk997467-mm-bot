#!/usr/bin/env python3
"""
CI check: enforce atomic JSON writer usage.
Scans repo for json.dump/json.dumps paired with open(...,'w') patterns.
Excludes: src/common/artifacts.py, src/common/jsonio.py, tests/.
Exit codes: 0 (ok), 2 (violations found).
"""

import os
import re
import sys


ALLOW = {
    os.path.normpath('src/common/artifacts.py'),
    os.path.normpath('src/common/jsonio.py'),
}


def scan_file(path: str) -> list:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception:
        return []
    out = []
    for i, line in enumerate(lines):
        if 'json.dump' in line or 'json.dumps' in line:
            # Look ±10 lines for open(...,'w')
            lo = max(0, i - 10)
            hi = min(len(lines), i + 11)
            window = ''.join(lines[lo:hi])
            if re.search(r"open\([^\)]*\b[wW][t\+]?\b", window):
                out.append((i + 1, line.strip()))
    return out


def main() -> int:
    violations = []
    for root, _, files in os.walk('.'):
        # Skip tests and hidden dirs
        if os.path.basename(root) == 'tests' or '/tests/' in root.replace('\\','/'):
            continue
        for name in files:
            if not name.endswith('.py'):
                continue
            path = os.path.normpath(os.path.join(root, name))
            if path in ALLOW:
                continue
            if path.startswith(os.path.normpath('./.')):
                continue
            hits = scan_file(path)
            if hits:
                violations.append((path, hits))

    if violations:
        for path, hits in violations:
            print(f"VIOLATION:{path}")
            for lineno, src in hits:
                print(f"  L{lineno}:{src}")
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())



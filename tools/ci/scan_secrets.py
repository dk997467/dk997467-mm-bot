import os
import re
import sys
from typing import List, Tuple

from src.common.redact import DEFAULT_PATTERNS


TARGET_DIRS = ['artifacts', 'dist', 'logs', 'config']
EXCLUDE_DIRS = {'venv', '.git', '__pycache__', 'tests/fixtures'}
TEXT_EXT = {'.txt', '.md', '.json', '.jsonl', '.yaml', '.yml', '.log', '.ini', ''}


def _is_text_file(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in TEXT_EXT


def _scan_file(path: str, patterns: List[str]) -> List[Tuple[int, str]]:
    hits: List[Tuple[int, str]] = []
    try:
        with open(path, 'r', encoding='ascii', errors='ignore') as f:
            for i, line in enumerate(f, start=1):
                s = line.rstrip('\n')
                for pat in patterns:
                    try:
                        if re.search(pat, s):
                            hits.append((i, s))
                            break
                    except re.error:
                        # ignore bad patterns
                        continue
    except Exception:
        return []
    return hits


def main(argv=None) -> int:
    patterns = list(DEFAULT_PATTERNS)
    found: List[Tuple[str, int, str]] = []
    for root in TARGET_DIRS:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # prune excludes
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                if not _is_text_file(path):
                    continue
                for (ln, s) in _scan_file(path, patterns):
                    found.append((path.replace('\\', '/'), ln, s))

    # deterministic order
    found.sort(key=lambda x: (x[0], x[1]))
    if found:
        for (p, ln, s) in found:
            # Do not print the secret itself; just show redacted and location
            from src.common.redact import redact
            red = redact(s, patterns)
            sys.stdout.write(f"SECRET? {p}:{ln}: {red}\n")
        sys.stdout.write('RESULT=FOUND\n')
        return 2
    else:
        sys.stdout.write('[OK] no secrets found\n')
        sys.stdout.write('RESULT=OK\n')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())



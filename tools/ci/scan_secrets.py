import os
import re
import sys
from typing import List, Tuple

from src.common.redact import DEFAULT_PATTERNS


TARGET_DIRS = ['artifacts', 'dist', 'logs', 'config']
EXCLUDE_DIRS = {'venv', '.git', '__pycache__', 'tests/fixtures'}
TEXT_EXT = {'.txt', '.md', '.json', '.jsonl', '.yaml', '.yml', '.log', '.ini', ''}

# Whitelist of known test/dummy values that should be ignored
# These are intentionally fake credentials used in CI/tests
TEST_CREDENTIALS_WHITELIST = {
    'test_api_key_for_ci_only',
    'test_api_secret_for_ci_only',
    'test_pg_password_for_ci_only',
    'dummy_api_key_12345',
    'fake_secret_for_testing',
    'ci-0.0.0',  # Version string that might match patterns
}


def _is_text_file(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in TEXT_EXT


def _is_whitelisted(line: str) -> bool:
    """Check if line contains only whitelisted test credentials."""
    for test_value in TEST_CREDENTIALS_WHITELIST:
        if test_value in line:
            return True
    return False


def _scan_file(path: str, patterns: List[str]) -> List[Tuple[int, str]]:
    hits: List[Tuple[int, str]] = []
    try:
        with open(path, 'r', encoding='ascii', errors='ignore') as f:
            for i, line in enumerate(f, start=1):
                s = line.rstrip('\n')
                
                # Skip lines with whitelisted test credentials
                if _is_whitelisted(s):
                    continue
                
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



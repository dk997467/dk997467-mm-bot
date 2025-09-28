import os
import re
import sys


def is_text_file(path: str) -> bool:
    # Simple heuristic: only lint .py files in src/ and tools/
    return (path.endswith('.py') and (path.startswith('src') or path.startswith('tools')))


def main() -> int:
    violations = []
    for root, _, files in os.walk('.'):
        # Skip venv and dist
        if any(seg in root for seg in ('/venv', '\\venv', '/dist', '\\dist')):
            continue
        for fn in files:
            path = os.path.join(root, fn).lstrip('./')
            if not is_text_file(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue
            # non-ASCII in string literals of print lines
            for m in re.finditer(r'print\(([^\)]*)\)', content):
                s = m.group(1)
                try:
                    s.encode('ascii')
                except Exception:
                    violations.append((path, 'non-ascii print content'))
    if violations:
        for p, msg in violations:
            print(f'ASCII_LINT {p}: {msg}')
        return 2
    print('ASCII_LINT OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())



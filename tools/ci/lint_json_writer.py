import os
import re
import sys


def should_scan(path: str) -> bool:
    if not path.endswith('.py'):
        return False
    
    # Skip research/strategy files - they use json.dump() for reports/calibration
    if any(segment in path for segment in ['/research/', '\\research\\', '/strategy/', '\\strategy\\']):
        return False
    
    if '/tests/' in path or '\\tests\\' in path:
        # allow tests if explicitly marked
        with open(path, 'r', encoding='utf-8') as f:
            head = f.read(4096)
            if '# test-ok: raw-json' in head or '# lint-ok: json-write' in head:
                return False
        return True
    
    # Check for marker comment in file header
    try:
        with open(path, 'r', encoding='utf-8') as f:
            head = f.read(4096)
            if '# lint-ok: json-write' in head or '# test-ok: raw-json' in head:
                return False
    except Exception:
        pass
    
    return True


def main() -> int:
    bad = []
    for root, _, files in os.walk('.'):
        if any(seg in root for seg in ('/venv', '\\venv', '/.venv', '\\.venv', '__pycache__')):
            continue
        for fn in files:
            path = os.path.join(root, fn)
            if path.startswith('./'):
                path = path[2:]
            if not should_scan(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue
            # Flag only file writes that bypass write_json_atomic
            uses_json_dump = re.search(r'\bjson\.dump\s*\(', content)
            writes_json_dumps = re.search(r'\.write\s*\([^)]*json\.dumps\s*\(', content)
            if (uses_json_dump or writes_json_dumps) and ('write_json_atomic' not in content):
                bad.append(path)
    if bad:
        for p in sorted(set(bad)):
            print(f'JSON_LINT violation in {p}')
        return 2
    print('JSON_LINT OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())



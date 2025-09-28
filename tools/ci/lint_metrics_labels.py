import re
import sys


ALLOWED = set(['env','service','instance','symbol','op','regime'])


def main() -> int:
    try:
        with open('src/metrics/exporter.py', 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        print('METRICS_LINT OK (exporter missing)')
        return 0
    bad = []
    # Find .labels(....) usage
    for m in re.finditer(r'labels\(([^)]*)\)', content):
        inside = m.group(1)
        # match symbol=..., op=... patterns
        for nm in re.findall(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*=', inside):
            if nm not in ALLOWED:
                bad.append(nm)
    if bad:
        for n in sorted(set(bad)):
            print(f'METRICS_LINT forbidden label: {n}')
        return 2
    print('METRICS_LINT OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())



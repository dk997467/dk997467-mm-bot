import json
import os
from typing import Any, Dict


def render_md(rep: Dict[str, Any]) -> str:
    lines = []
    lines.append('EDGE SENTINEL REPORT\n')
    lines.append('\n')
    lines.append('| symbol | gross_bps | fees_eff_bps | adverse_bps | slippage_bps | inventory_bps | net_bps | fills | turnover_usd |\n')
    lines.append('|--------|-----------|--------------|-------------|---------------|----------------|---------|-------|---------------|\n')
    syms = sorted(rep.get('summary', {}).get('symbols', {}).keys())
    for s in syms:
        m = rep['summary']['symbols'][s]
        lines.append('| ' + s + ' | ' + '%.6f' % m['gross_bps'] + ' | ' + '%.6f' % m['fees_eff_bps'] + ' | ' + '%.6f' % m['adverse_bps'] + ' | ' + '%.6f' % m['slippage_bps'] + ' | ' + '%.6f' % m['inventory_bps'] + ' | ' + '%.6f' % m['net_bps'] + ' | ' + str(int(m['fills'])) + ' | ' + '%.6f' % m['turnover_usd'] + ' |\n')
    lines.append('\n')
    lines.append('Advice:\n')
    for a in rep.get('advice', []):
        lines.append('- ' + a + '\n')
    return ''.join(lines)


def main(argv=None) -> int:
    with open('artifacts/EDGE_SENTINEL.json', 'r', encoding='ascii') as f:
        rep = json.load(f)
    md = render_md(rep)
    path = 'artifacts/EDGE_SENTINEL.md'
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write(md)
        if not md.endswith('\n'):
            f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)
    try:
        from src.common.eol import normalize_eol  # type: ignore
        normalize_eol(path, style="crlf", ensure_trailing=3)
    except Exception:
        pass
    print('EDGE_SENTINEL WROTE artifacts/EDGE_SENTINEL.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



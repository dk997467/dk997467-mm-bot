import argparse
import os
import sys
from typing import Any, Dict

from tools.edge_audit import build_report, write_json_atomic


def _write_text_atomic(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        f.write(content)
        if not content.endswith('\n'):
            f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def _render_md(rep: Dict[str, Any]) -> str:
    lines = []
    lines.append('EDGE REPORT\n')
    lines.append('\n')
    lines.append('| symbol | gross_bps | fees_eff_bps | adverse_bps | slippage_bps | inventory_bps | net_bps | fills | turnover_usd |\n')
    lines.append('|--------|-----------|--------------|-------------|---------------|----------------|---------|-------|---------------|\n')
    for sym in sorted(rep.get('symbols', {}).keys()):
        s = rep['symbols'][sym]
        lines.append('| ' + sym + ' | ' + '%.6f' % s['gross_bps'] + ' | ' + '%.6f' % s['fees_eff_bps'] + ' | ' + '%.6f' % s['adverse_bps'] + ' | ' + '%.6f' % s['slippage_bps'] + ' | ' + '%.6f' % s['inventory_bps'] + ' | ' + '%.6f' % s['net_bps'] + ' | ' + str(int(s['fills'])) + ' | ' + '%.6f' % s['turnover_usd'] + ' |\n')
    t = rep.get('total', {})
    lines.append('| TOTAL | ' + '%.6f' % t.get('gross_bps', 0.0) + ' | ' + '%.6f' % t.get('fees_eff_bps', 0.0) + ' | ' + '%.6f' % t.get('adverse_bps', 0.0) + ' | ' + '%.6f' % t.get('slippage_bps', 0.0) + ' | ' + '%.6f' % t.get('inventory_bps', 0.0) + ' | ' + '%.6f' % t.get('net_bps', 0.0) + ' | ' + str(int(t.get('fills', 0.0))) + ' | ' + '%.6f' % t.get('turnover_usd', 0.0) + ' |\n')
    return ''.join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--trades', required=True)
    ap.add_argument('--quotes', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)

    rep = build_report(args.trades, args.quotes)
    # Prefer deterministic artifact writer with CRLF+3
    try:
        from src.common.jsonio import dump_json_artifact  # type: ignore
        dump_json_artifact(args.out, rep)
    except Exception:
        write_json_atomic(args.out, rep)
        # Manual CRLF+3 normalization
        try:
            txt = open(args.out, 'r', encoding='ascii').read()
            txt = txt.replace('\r\n', '\n').replace('\r', '\n')
            txt = txt.rstrip('\n') + '\r\n\r\n\r\n'
            open(args.out, 'wb').write(txt.encode('ascii'))
        except Exception:
            pass
    md_path = os.path.splitext(args.out)[0] + '.md'
    md = _render_md(rep)
    _write_text_atomic(md_path, md)
    # Manual CRLF+3 normalization for MD
    try:
        txt = open(md_path, 'r', encoding='ascii').read()
        txt = txt.replace('\r\n', '\n').replace('\r', '\n')
        txt = txt.rstrip('\n') + '\r\n\r\n\r\n'
        open(md_path, 'wb').write(txt.encode('ascii'))
    except Exception:
        pass

    size = os.path.getsize(args.out)
    print('wrote', args.out, 'size', size)
    print('wrote', md_path, 'size', os.path.getsize(md_path))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



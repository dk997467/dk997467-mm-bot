import argparse
import json
import os
from typing import Any, Dict

import yaml

from src.region.canary import parse_jsonl, compare


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        json.dump(data, f, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


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


def _render_md(report: Dict[str, Any]) -> str:
    lines = []
    lines.append('Region Canary Comparison\n')
    lines.append('\n')
    lines.append('| region | net_bps | order_age_p95_ms | fill_rate | taker_share_pct |\n')
    lines.append('|--------|---------|------------------|-----------|------------------|\n')
    for reg in sorted(report.get('regions', {}).keys()):
        m = report['regions'][reg]
        lines.append('| ' + reg + ' | ' + '%.6f' % m['net_bps'] + ' | ' + '%.6f' % m['order_age_p95_ms'] + ' | ' + '%.6f' % m['fill_rate'] + ' | ' + '%.6f' % m['taker_share_pct'] + ' |\n')
    lines.append('\n')
    lines.append('| window | net_bps | order_age_p95_ms | fill_rate | taker_share_pct |\n')
    lines.append('|--------|---------|------------------|-----------|------------------|\n')
    for win in sorted(report.get('windows', {}).keys()):
        m = report['windows'][win]
        lines.append('| ' + win + ' | ' + '%.6f' % m['net_bps'] + ' | ' + '%.6f' % m['order_age_p95_ms'] + ' | ' + '%.6f' % m['fill_rate'] + ' | ' + '%.6f' % m['taker_share_pct'] + ' |\n')
    w = report.get('winner', {})
    lines.append('\nWinner: ' + (w.get('region','') or '') + ' @ ' + (w.get('window','') or '') + '\n')
    return ''.join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--regions', required=True)
    ap.add_argument('--in', dest='in_path', required=True)
    ap.add_argument('--out', dest='out_path', required=True)
    args = ap.parse_args(argv)

    with open(args.regions, 'r', encoding='ascii') as f:
        cfg = yaml.safe_load(f)
    regions = cfg.get('regions', [])
    switch = cfg.get('switch', {})
    safe = (switch or {}).get('safe_thresholds', {})

    recs = parse_jsonl(args.in_path)
    report = compare(recs, regions, safe)

    _write_json_atomic(args.out_path, report)
    md_path = os.path.splitext(args.out_path)[0] + '.md'
    _write_text_atomic(md_path, _render_md(report))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())



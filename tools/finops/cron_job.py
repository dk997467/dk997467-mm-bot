import argparse
import os
import sys
from datetime import datetime, timezone

from tools.finops.exporter import (
    load_artifacts,
    export_pnl_csv,
    export_fees_csv,
    export_turnover_csv,
    export_latency_csv,
    export_edge_csv,
)
from tools.finops.reconcile import reconcile, render_reconcile_md, write_json_atomic


def _now_utc_iso_compact() -> str:
    if os.environ.get('MM_FREEZE_UTC') == '1':
        return '19700101T000000Z'
    dt = datetime.now(timezone.utc)
    return dt.strftime('%Y%m%dT%H%M%SZ')


def _default_out_dir() -> str:
    tag = _now_utc_iso_compact()
    return os.path.join('dist', 'finops', tag)


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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog='finops-cron', add_help=True)
    p.add_argument('--artifacts', required=True, help='Path to artifacts metrics.json')
    p.add_argument('--exchange-dir', required=True, help='Directory with exchange CSV reports')
    p.add_argument('--out-dir', default=_default_out_dir(), help='Output directory for CSV/JSON/MD')
    args = p.parse_args(argv)

    art = load_artifacts(args.artifacts)
    out = args.out_dir
    os.makedirs(out, exist_ok=True)

    # Export CSVs
    export_pnl_csv(art, os.path.join(out, 'pnl.csv'))
    export_fees_csv(art, os.path.join(out, 'fees.csv'))
    export_turnover_csv(art, os.path.join(out, 'turnover.csv'))
    export_latency_csv(art, os.path.join(out, 'latency.csv'))
    export_edge_csv(art, os.path.join(out, 'edge.csv'))

    # Reconcile
    rep = reconcile(args.artifacts, args.exchange_dir)
    write_json_atomic(os.path.join(out, 'reconcile_report.json'), rep)
    diff_md = render_reconcile_md(rep)
    _write_text_atomic(os.path.join(out, 'reconcile_diff.md'), diff_md)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())



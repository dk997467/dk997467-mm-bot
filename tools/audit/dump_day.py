import argparse
import json
import os


def _write_atomic(path: str, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='ascii', newline='') as f:
        for ln in lines:
            if not ln.endswith('\n'):
                ln = ln + '\n'
            f.write(ln)
        f.flush(); os.fsync(f.fileno())
    if os.path.exists(path):
        os.replace(tmp, path)
    else:
        os.rename(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--audit', default='artifacts/audit.jsonl')
    ap.add_argument('--utc-date', required=True)  # YYYY-MM-DD
    ap.add_argument('--out', default='artifacts/AUDIT_DUMP.jsonl')
    args = ap.parse_args(argv)

    lines = []
    try:
        with open(args.audit, 'r', encoding='ascii') as f:
            for ln in f:
                try:
                    rec = json.loads(ln)
                except Exception:
                    continue
                ts = str(rec.get('ts', ''))
                if ts.startswith(args.utc_date):
                    # write as-is
                    if not ln.endswith('\n'):
                        ln = ln + '\n'
                    lines.append(ln)
    except FileNotFoundError:
        pass

    _write_atomic(args.out, lines)
    try:
        from src.common.eol import normalize_eol  # type: ignore
        normalize_eol(args.out, style="crlf", ensure_trailing=3)
    except Exception:
        pass
    print('AUDIT_DUMP', args.utc_date, len(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



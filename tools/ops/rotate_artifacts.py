import argparse
import os
import re
import sys
import time
from typing import Dict, List, Tuple


def _norm(path: str) -> str:
    return path.replace('\\', '/')


def _unit_size(path: str) -> int:
    if os.path.isdir(path):
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                p = os.path.join(root, f)
                try:
                    total += os.path.getsize(p)
                except Exception:
                    pass
        return total
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def _extract_age_ts(path: str) -> float:
    # Try date in filename: YYYYMMDD[THHMMSSZ]
    base = os.path.basename(path)
    m = re.search(r'(\d{8})(T\d{6}Z)?', base)
    if m:
        s = m.group(1)
        try:
            y, mo, d = int(s[:4]), int(s[4:6]), int(s[6:8])
            import datetime as dt
            return dt.datetime(y, mo, d, tzinfo=dt.timezone.utc).timestamp()
        except Exception:
            pass
    # Fallback mtime
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


def _gather_units(roots: List[str]) -> List[Tuple[str, bool, float, int]]:
    units: List[Tuple[str, bool, float, int]] = []  # (path, is_dir, age_ts, size)
    for root in roots:
        if not os.path.exists(root):
            continue
        # Special: dist/finops/<ts> as units
        finops_root = os.path.join(root, 'finops') if os.path.basename(root) == 'dist' else None
        if finops_root and os.path.isdir(finops_root):
            for name in sorted(os.listdir(finops_root)):
                p = os.path.join(finops_root, name)
                if os.path.isdir(p):
                    age_ts = _extract_age_ts(p)
                    size = _unit_size(p)
                    units.append((p, True, age_ts, size))
        # Other files under root as units
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip finops subdirs already added
            if finops_root and _norm(dirpath).startswith(_norm(finops_root)):
                continue
            for f in filenames:
                p = os.path.join(dirpath, f)
                age_ts = _extract_age_ts(p)
                size = _unit_size(p)
                units.append((p, False, age_ts, size))
    return units


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--roots', nargs='+', required=True)
    ap.add_argument('--keep-days', type=int, default=14)
    ap.add_argument('--max-size-gb', type=float, default=2.0)
    ap.add_argument('--archive-dir', default='dist/archives')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args(argv)

    roots = args.roots
    keep_sec = max(0, int(args.keep_days)) * 86400
    max_bytes = int(float(args.max_size_gb) * (1024**3))
    now = time.time()

    units = _gather_units(roots)
    # Stable sort by (age_ts, path)
    units.sort(key=lambda x: (x[2], _norm(x[0])))

    # Stage A: age-based deletion
    remaining = []
    total_size = 0
    for path, is_dir, age_ts, size in units:
        age_ok = (now - age_ts) <= keep_sec
        if not age_ok:
            print('DEL_AGE', 'DIR' if is_dir else 'FILE', _norm(path), 'size=' + str(size), 'age_ts=' + str(int(age_ts)))
            if not args.dry_run:
                try:
                    if is_dir:
                        import shutil
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
                except Exception:
                    pass
        else:
            remaining.append((path, is_dir, age_ts, size))
            total_size += size

    # Stage B: size-based deletion on remaining
    remaining.sort(key=lambda x: (x[2], _norm(x[0])))
    idx = 0
    while total_size > max_bytes and idx < len(remaining):
        path, is_dir, age_ts, size = remaining[idx]
        print('DEL_SIZE', 'DIR' if is_dir else 'FILE', _norm(path), 'size=' + str(size), 'age_ts=' + str(int(age_ts)))
        if not args.dry_run:
            try:
                if is_dir:
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
            except Exception:
                pass
        total_size -= size
        idx += 1

    print('ROTATION=' + ('DRYRUN' if args.dry_run else 'OK'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



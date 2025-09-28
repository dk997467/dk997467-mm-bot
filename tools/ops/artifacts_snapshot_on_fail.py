#!/usr/bin/env python3
"""
Snapshot artifacts on last FAIL in SOAK_JOURNAL.jsonl (stdlib-only).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .artifacts_archive import copy_tree_ascii, ensure_dir


def _read_last(path: str):
    try:
        with open(path, 'r', encoding='ascii') as f:
            last = None
            for line in f:
                if line.strip():
                    last = line
            if last:
                return json.loads(last)
    except Exception:
        return None
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--journal', default='artifacts/SOAK_JOURNAL.jsonl')
    ap.add_argument('--src', default='artifacts')
    ap.add_argument('--dst-root', default='artifacts/failures')
    ap.add_argument('--fast', action='store_true', default=True)
    args = ap.parse_args(argv)

    rec = _read_last(args.journal)
    if not rec or str(rec.get('status')) != 'FAIL':
        print('event=snapshot_on_fail status=SKIP')
        return 0

    ts = rec.get('ts') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    # Make dir name timestamp-friendly
    safe = ts.replace(':', '').replace('T', '_').replace('Z', '')
    snap_dir = str(Path(args.dst_root) / safe)
    ensure_dir(snap_dir)

    def _winpath(p: str) -> str:
        import os as _os
        try:
            return ('\\\\?\\' + _os.path.abspath(p)) if _os.name == 'nt' else p
        except Exception:
            return p

    copied = 0
    skipped = 0

    if args.fast:
        ALLOWLIST_FILES = {
            'KPI_GATE.json',
            'FULL_STACK_VALIDATION.json',
            'EDGE_REPORT.json',
            'EDGE_SENTINEL.json',
            'RELEASE_STAMP.json',
            'SOAK_JOURNAL.jsonl',
        }
        ALLOWLIST_EXTS = {'.json', '.jsonl', '.md', '.log'}
        MAX_SIZE = 5 * 1024 * 1024
        MAX_FILES = 300

        src_root = Path(args.src)
        dst_root = Path(snap_dir)

        # 1) Key files first
        for name in ALLOWLIST_FILES:
            if copied >= MAX_FILES:
                break
            sp = src_root / name
            if not sp.exists() or not sp.is_file():
                continue
            try:
                rel = sp.relative_to(src_root)
            except Exception:
                rel = Path(name)
            dp = dst_root / rel
            try:
                ensure_dir(str(dp.parent))
                shutil.copy2(_winpath(str(sp)), _winpath(str(dp)))
                copied += 1
            except Exception as exc:
                print(f"event=snapshot_skip path={rel.as_posix()} reason={type(exc).__name__}")
                skipped += 1

        # 2) Walk allowed light files up to MAX_FILES
        for root, dirs, files in os.walk(src_root):
            if copied >= MAX_FILES:
                break
            root_path = Path(root)
            for fname in files:
                if copied >= MAX_FILES:
                    break
                sp = root_path / fname
                try:
                    ext = sp.suffix.lower()
                    if ext not in ALLOWLIST_EXTS:
                        continue
                    try:
                        sz = sp.stat().st_size
                    except Exception:
                        sz = 0
                    if sz > MAX_SIZE:
                        print(f"WARN skip_large path={sp} bytes={sz}")
                        skipped += 1
                        continue
                    try:
                        rel = sp.relative_to(src_root)
                    except Exception:
                        rel = Path(fname)
                    dp = dst_root / rel
                    try:
                        ensure_dir(str(dp.parent))
                        shutil.copy2(_winpath(str(sp)), _winpath(str(dp)))
                        copied += 1
                    except Exception as exc:
                        print(f"event=snapshot_skip path={rel.as_posix()} reason={type(exc).__name__}")
                        skipped += 1
                except Exception as exc:
                    # Any unexpected per-file error -> skip
                    try:
                        rel = sp.relative_to(src_root)
                    except Exception:
                        rel = Path(fname)
                    print(f"event=snapshot_skip path={rel.as_posix()} reason={type(exc).__name__}")
                    skipped += 1

    else:
        # Full archive with existing helper (per-file protected, skips >5MB)
        try:
            n = copy_tree_ascii(args.src, snap_dir)
            copied = int(n)
            # skipped is not tracked in full mode; leave as 0
        except Exception:
            copied = 0
            # best-effort; do not fail

    print(f'event=snapshot_on_fail status=FAIL snap_dir={snap_dir} files={copied} skipped={skipped}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



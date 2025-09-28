#!/usr/bin/env python3
"""
Canonize JSON files: deterministic ASCII JSON with sorted keys and compact separators.

Modes:
  --mode=check  → exit 0 if all files are canonical; 1 otherwise
  --mode=fix    → rewrite non-canonical files atomically (fsync), then exit 0

Rules:
- ensure_ascii=True, sort_keys=True, separators=(",", ":"), trailing "\n"
- stdlib-only; ASCII I/O; LF endings
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable, List


def _gather_json_files(paths: List[str]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_file() and pp.suffix.lower() == ".json":
            out.append(pp)
        elif pp.is_dir():
            for root, _dirs, files in os.walk(pp):
                for name in files:
                    if name.lower().endswith(".json"):
                        out.append(Path(root) / name)
    # Deterministic order
    return sorted(set(out), key=lambda x: str(x).lower())


def _canon_bytes(obj) -> bytes:
    s = json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    return s.encode("ascii", errors="strict")


def _write_atomic_ascii(path: Path, data: bytes) -> None:
    sp = str(path)
    p = Path(sp)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    tmp = sp + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    try:
        os.replace(tmp, sp)
    except Exception:
        os.rename(tmp, sp)
    try:
        dfd = os.open(str(p.parent), os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        pass


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["check", "fix"], required=True)
    ap.add_argument("paths", nargs="+", help="Files or directories to process")
    args = ap.parse_args(argv)

    files = _gather_json_files(args.paths)
    non_canon: List[Path] = []
    for fp in files:
        try:
            raw = fp.read_bytes()
            text = raw.decode("ascii", errors="strict")
            obj = json.loads(text)
            want = _canon_bytes(obj)
            if raw != want:
                non_canon.append(fp)
                if args.mode == "fix":
                    _write_atomic_ascii(fp, want)
        except Exception:
            # Consider unreadable/bad JSON as non-canonical in check mode; in fix mode, skip rewrite
            non_canon.append(fp)

    if args.mode == "check":
        if non_canon:
            for p in non_canon:
                print(f"NON_CANON:{p}")
            print("CANON=NEEDS_FIX")
            return 1
        print("CANON=OK")
        return 0

    # fix mode
    if non_canon:
        print("CANON=FIXED")
    else:
        print("CANON=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



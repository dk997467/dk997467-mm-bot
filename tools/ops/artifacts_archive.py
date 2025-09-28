from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path
import os
from typing import Iterable, Tuple

ALLOWED_EXT = {".json", ".jsonl", ".md", ".log"}


def _should_skip_dir(dirpath: str, exclude: Iterable[str]) -> bool:
    dp = dirpath.replace("\\", "/")
    for ex in (exclude or []):
        exn = str(ex).replace("\\", "/").strip("/").lower()
        if not exn:
            continue
        if f"/{exn}/" in f"/{dp.strip('/')}/" or dp.lower().endswith("/" + exn):
            return True
    return False


def copy_tree_fast(src: Path, dst: Path, exclude: Iterable[str], max_files: int, max_mb: int) -> Tuple[int, int]:
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    max_bytes = max_mb * 1024 * 1024
    total_bytes = 0
    try:
        for root, dirs, files in os.walk(src, topdown=True):
            # prune excluded dirs early
            dirs[:] = [d for d in dirs if not _should_skip_dir(os.path.join(root, d), exclude)]
            if _should_skip_dir(root, exclude):
                continue
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext not in ALLOWED_EXT:
                    continue
                if copied >= max_files or total_bytes >= max_bytes:
                    return copied, skipped
                src_file = os.path.join(root, name)
                rel = os.path.relpath(src_file, start=src)
                dst_file = os.path.join(dst, rel)
                try:
                    try:
                        size = os.path.getsize(src_file)
                    except Exception:
                        size = 0
                    if size > max_bytes or total_bytes + size > max_bytes:
                        return copied, skipped
                    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                    with open(src_file, "rb") as fin, open(dst_file, "wb") as fout:
                        while True:
                            chunk = fin.read(1024 * 1024)
                            if not chunk:
                                break
                            fout.write(chunk)
                    copied += 1
                    total_bytes += size
                except Exception:
                    skipped += 1
                    continue
    except KeyboardInterrupt:
        # graceful exit without traceback
        pass
    return copied, skipped


def copy_tree_full(src: Path, dst: Path, exclude: Iterable[str]) -> Tuple[int, int]:
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    for root, dirs, files in os.walk(src, topdown=True):
        dirs[:] = [d for d in dirs if not _should_skip_dir(os.path.join(root, d), exclude)]
        if _should_skip_dir(root, exclude):
            continue
        for name in files:
            src_file = os.path.join(root, name)
            rel = os.path.relpath(src_file, start=src)
            dst_file = os.path.join(dst, rel)
            try:
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                # full copy in chunks
                with open(src_file, "rb") as fin, open(dst_file, "wb") as fout:
                    while True:
                        chunk = fin.read(1024 * 1024)
                        if not chunk:
                            break
                        fout.write(chunk)
                copied += 1
            except Exception:
                skipped += 1
                continue
    return copied, skipped


def _str2bool(v):
    return str(v).strip().lower() != "false"


def main() -> int:
    ap = argparse.ArgumentParser(description="Archive artifacts (fast by default).")
    ap.add_argument("--src", default="artifacts")
    ap.add_argument("--dst", default=None)
    ap.add_argument("--fast", type=_str2bool, default=True)
    ap.add_argument("--exclude", action="append", default=["failures", "archive"])
    ap.add_argument("--max-files", type=int, default=300)
    ap.add_argument("--max-mb", type=int, default=5)
    args = ap.parse_args()

    src = Path(args.src)
    if args.dst is None:
        ts = time.strftime("%Y-%m-%d_%H%M%S", time.gmtime())
        dst = Path("artifacts") / "archive" / ts
    else:
        dst = Path(args.dst)

    if args.fast:
        copied, skipped = copy_tree_fast(src, dst, args.exclude, args.max_files, args.max_mb)
    else:
        copied, skipped = copy_tree_full(src, dst, args.exclude)

    print(f"event=archive status=OK files={copied} skipped={skipped} dst={dst}")
    return 0


# Back-compat helpers for existing imports
def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def copy_tree_ascii(src_dir: str, dst_dir: str, *, include_exts: tuple[str, ...] = (".json", ".md", ".log"), max_bytes: int = 5_000_000) -> int:
    src = Path(src_dir)
    dst = Path(dst_dir)
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        try:
            ext = p.suffix.lower()
            if ext not in set(include_exts):
                continue
            try:
                sz = p.stat().st_size
            except Exception:
                sz = 0
            if sz > max_bytes:
                print(f"WARN skip_large path={p} bytes={sz}")
                continue
            rel = p.relative_to(src)
            outp = dst / rel
            outp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(p), str(outp))
            copied += 1
        except Exception:
            continue
    return copied


if __name__ == "__main__":
    raise SystemExit(main())
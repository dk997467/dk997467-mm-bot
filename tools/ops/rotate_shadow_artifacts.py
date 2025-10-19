#!/usr/bin/env python3
"""
Shadow Artifact Rotation

Keeps last N ITER_SUMMARY files, archives older ones to timestamped directory.

Usage:
    python -m tools.ops.rotate_shadow_artifacts
    python -m tools.ops.rotate_shadow_artifacts --max-keep 300 --src artifacts/shadow/latest
"""

import argparse
import shutil
import time
from pathlib import Path


MAX_KEEP_DEFAULT = 300
SRC_DEFAULT = "artifacts/shadow/latest"
DST_ROOT_DEFAULT = "artifacts/shadow"


def rotate_shadow_artifacts(
    src: str = SRC_DEFAULT,
    dst_root: str = DST_ROOT_DEFAULT,
    max_keep: int = MAX_KEEP_DEFAULT,
) -> None:
    """
    Rotate shadow artifacts: keep last N, archive older.
    
    Args:
        src: Source directory with ITER_SUMMARY files
        dst_root: Root directory for archives
        max_keep: Maximum files to keep in src (default: 300)
    """
    src_path = Path(src)
    dst_root_path = Path(dst_root)
    
    if not src_path.exists():
        print(f"[SKIP] Source directory not found: {src}")
        return
    
    # Find all ITER_SUMMARY files (sorted by name = sorted by iteration)
    files = sorted(src_path.glob("ITER_SUMMARY_*.json"))
    
    if not files:
        print(f"[SKIP] No ITER_SUMMARY files found in {src}")
        return
    
    print(f"[INFO] Found {len(files)} ITER_SUMMARY files in {src}")
    
    if len(files) <= max_keep:
        print(f"[SKIP] No rotation needed (count={len(files)} <= max_keep={max_keep})")
        return
    
    # Create timestamped archive directory
    ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    dst = dst_root_path / f"ts-{ts}"
    dst.mkdir(parents=True, exist_ok=True)
    
    # Move older files (keep last max_keep)
    to_move = files[:-max_keep]
    
    print(f"[ROTATE] Moving {len(to_move)} files to {dst}")
    
    for fp in to_move:
        shutil.move(str(fp), str(dst / fp.name))
    
    # Copy snapshot for reference (if exists)
    snapshot = src_path / "reports" / "analysis" / "POST_SHADOW_SNAPSHOT.json"
    if snapshot.exists():
        shutil.copy2(str(snapshot), str(dst / snapshot.name))
        print(f"[COPY] Snapshot copied to archive")
    
    # Copy audit summary (if exists)
    audit = src_path / "reports" / "analysis" / "POST_SHADOW_AUDIT_SUMMARY.json"
    if audit.exists():
        shutil.copy2(str(audit), str(dst / audit.name))
        print(f"[COPY] Audit summary copied to archive")
    
    print(f"[OK] Archived {len(to_move)} files to {dst}")
    print(f"[OK] Kept {max_keep} most recent files in {src}")
    
    # Summary
    remaining = sorted(src_path.glob("ITER_SUMMARY_*.json"))
    print(f"[SUMMARY] Remaining in {src}: {len(remaining)} files")


def main():
    parser = argparse.ArgumentParser(
        description="Rotate shadow artifacts: keep last N, archive older"
    )
    parser.add_argument(
        "--src",
        default=SRC_DEFAULT,
        help=f"Source directory (default: {SRC_DEFAULT})"
    )
    parser.add_argument(
        "--dst-root",
        default=DST_ROOT_DEFAULT,
        help=f"Archive root directory (default: {DST_ROOT_DEFAULT})"
    )
    parser.add_argument(
        "--max-keep",
        type=int,
        default=MAX_KEEP_DEFAULT,
        help=f"Maximum files to keep (default: {MAX_KEEP_DEFAULT})"
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("SHADOW ARTIFACT ROTATION")
    print("=" * 80)
    print(f"Source: {args.src}")
    print(f"Archive root: {args.dst_root}")
    print(f"Max keep: {args.max_keep}")
    print()
    
    rotate_shadow_artifacts(
        src=args.src,
        dst_root=args.dst_root,
        max_keep=args.max_keep,
    )
    
    print()
    print("=" * 80)
    print("ROTATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()


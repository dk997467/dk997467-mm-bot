#!/usr/bin/env python3
"""
Artifact Rotation & Cleanup Tool

Removes old artifacts based on TTL, size, and count limits.

Usage:
    # Dry run
    python -m tools.ops.rotate_artifacts --days 7 --max-size 2G --keep 100 --dry-run
    
    # Real cleanup
    python -m tools.ops.rotate_artifacts --days 7 --max-size 2G --keep 100
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple


def parse_size(size_str: str) -> int:
    """Parse size string (e.g., '2G', '500M') to bytes."""
    size_str = size_str.upper().strip()
    
    if size_str.endswith('G'):
        return int(float(size_str[:-1]) * 1024 * 1024 * 1024)
    elif size_str.endswith('M'):
        return int(float(size_str[:-1]) * 1024 * 1024)
    elif size_str.endswith('K'):
        return int(float(size_str[:-1]) * 1024)
    else:
        return int(size_str)


def get_file_age_days(path: Path) -> float:
    """Get file age in days."""
    mtime = path.stat().st_mtime
    age_seconds = datetime.now().timestamp() - mtime
    return age_seconds / 86400.0


def scan_artifacts(base_dir: str = "artifacts") -> List[Tuple[Path, float, int]]:
    """
    Scan artifacts directory and return list of (path, age_days, size_bytes).
    """
    if not Path(base_dir).exists():
        return []
    
    files = []
    for root, dirs, filenames in os.walk(base_dir):
        # Skip .git and hidden dirs
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for filename in filenames:
            path = Path(root) / filename
            try:
                age_days = get_file_age_days(path)
                size_bytes = path.stat().st_size
                files.append((path, age_days, size_bytes))
            except Exception:
                # Skip files that can't be accessed
                continue
    
    return files


def apply_ttl_filter(files: List[Tuple[Path, float, int]], max_days: int) -> List[Path]:
    """Filter files older than max_days."""
    return [f[0] for f in files if f[1] > max_days]


def apply_size_filter(files: List[Tuple[Path, float, int]], max_size: int) -> List[Path]:
    """Filter files if total size exceeds max_size (oldest first)."""
    # Sort by age (oldest first)
    sorted_files = sorted(files, key=lambda x: x[1], reverse=True)
    
    total_size = sum(f[2] for f in files)
    to_delete = []
    
    while total_size > max_size and sorted_files:
        oldest = sorted_files.pop(0)
        to_delete.append(oldest[0])
        total_size -= oldest[2]
    
    return to_delete


def apply_count_filter(files: List[Tuple[Path, float, int]], max_count: int) -> List[Path]:
    """Keep only max_count newest files."""
    if len(files) <= max_count:
        return []
    
    # Sort by age (newest first)
    sorted_files = sorted(files, key=lambda x: x[1])
    
    # Delete oldest files beyond max_count
    to_delete = [f[0] for f in sorted_files[max_count:]]
    return to_delete


def format_size(size_bytes: int) -> str:
    """Format size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}TB"


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Rotate and cleanup artifacts")
    parser.add_argument("--days", type=int, help="Delete files older than N days")
    parser.add_argument("--max-size", type=str, help="Max total size (e.g., '2G')")
    parser.add_argument("--keep", type=int, help="Keep only N newest files")
    parser.add_argument("--base-dir", default="artifacts", help="Base directory")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (don't delete)")
    args = parser.parse_args(argv)
    
    # Validation
    if not any([args.days, args.max_size, args.keep]):
        print("[ERROR] At least one of --days, --max-size, or --keep required")
        return 1
    
    print("\n" + "="*60)
    print("ARTIFACT ROTATION" + (" (DRY RUN)" if args.dry_run else ""))
    print("="*60 + "\n")
    
    # Scan files
    print(f"[SCAN] Scanning {args.base_dir}/...")
    files = scan_artifacts(args.base_dir)
    total_size = sum(f[2] for f in files)
    
    print(f"[SCAN] Found {len(files)} files ({format_size(total_size)} total)\n")
    
    # Apply filters
    to_delete = set()
    
    if args.days:
        print(f"[TTL] Applying TTL filter (>{args.days} days)...")
        ttl_delete = apply_ttl_filter(files, args.days)
        to_delete.update(ttl_delete)
        print(f"[TTL] Marked {len(ttl_delete)} files for deletion\n")
    
    if args.max_size:
        max_size_bytes = parse_size(args.max_size)
        print(f"[SIZE] Applying size filter (max {format_size(max_size_bytes)})...")
        size_delete = apply_size_filter(files, max_size_bytes)
        to_delete.update(size_delete)
        print(f"[SIZE] Marked {len(size_delete)} files for deletion\n")
    
    if args.keep:
        print(f"[COUNT] Applying count filter (keep {args.keep} newest)...")
        count_delete = apply_count_filter(files, args.keep)
        to_delete.update(count_delete)
        print(f"[COUNT] Marked {len(count_delete)} files for deletion\n")
    
    # Execute deletion
    if not to_delete:
        print("[OK] No files to delete\n")
        return 0
    
    print(f"[DELETE] {len(to_delete)} files to delete:")
    deleted_size = 0
    deleted_count = 0
    
    for path in sorted(to_delete):
        try:
            size = path.stat().st_size
            age = get_file_age_days(path)
            print(f"  - {path} ({format_size(size)}, {age:.1f} days old)")
            
            if not args.dry_run:
                path.unlink()
                deleted_size += size
                deleted_count += 1
        except Exception as e:
            print(f"  ! Failed to delete {path}: {e}")
    
    print()
    if args.dry_run:
        print(f"[DRY RUN] Would delete {len(to_delete)} files ({format_size(sum(f[2] for f in files if f[0] in to_delete))})")
    else:
        print(f"[DONE] Deleted {deleted_count} files ({format_size(deleted_size)})")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

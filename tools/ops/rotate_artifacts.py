#!/usr/bin/env python3
"""
Artifact Rotation & Cleanup Tool

Removes old artifacts based on TTL, size, and count limits.

Usage:
    # Dry run (new style)
    python -m tools.ops.rotate_artifacts --days 7 --max-size 2G --keep 100 --dry-run
    
    # Dry run (old style)
    python -m tools.ops.rotate_artifacts --roots artifacts dist --keep-days 7 --dry-run
    
    # Real cleanup with archiving
    python -m tools.ops.rotate_artifacts --roots artifacts --keep 100 --archive-dir archives/
"""

import argparse
import os
import sys
import zipfile
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


def create_archive(files_to_archive: List[Path], archive_dir: str, dry_run: bool = False) -> str:
    """
    Archive files before deletion.
    
    Returns path to created archive.
    """
    if dry_run:
        return f"{archive_dir}/archive_dryrun.zip"
    
    # Create archive directory
    Path(archive_dir).mkdir(parents=True, exist_ok=True)
    
    # Archive name with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = f"{archive_dir}/artifacts_{timestamp}.zip"
    
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in files_to_archive:
            if file_path.exists():
                # Preserve directory structure in archive
                arcname = str(file_path)
                zf.write(file_path, arcname)
    
    return archive_path


def main(argv=None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Rotate and cleanup artifacts")
    
    # New-style flags (current)
    parser.add_argument("--days", type=int, help="Delete files older than N days")
    parser.add_argument("--max-size", type=str, help="Max total size (e.g., '2G')")
    parser.add_argument("--keep", type=int, help="Keep only N newest files")
    parser.add_argument("--base-dir", default="artifacts", help="Base directory")
    
    # Old-style flags (compatibility aliases)
    parser.add_argument("--roots", nargs="+", help="Root directories to scan (alias to base-dir)")
    parser.add_argument("--keep-days", type=int, help="Delete files older than N days (alias to --days)")
    parser.add_argument("--max-size-gb", type=float, help="Max total size in GB (alias to --max-size)")
    parser.add_argument("--archive-dir", type=str, help="Archive files before deletion")
    
    # Common flags
    parser.add_argument("--dry-run", action="store_true", help="Dry run (don't delete)")
    
    args = parser.parse_args(argv)
    
    # Handle alias flags (old-style to new-style mapping)
    if args.roots:
        # Multiple roots override base-dir
        scan_dirs = args.roots
    else:
        scan_dirs = [args.base_dir]
    
    # Map old flags to new (handle both sets of flags)
    max_days = None
    if args.keep_days is not None:
        max_days = args.keep_days
    elif args.days is not None:
        max_days = args.days
    
    max_size_bytes = None
    if args.max_size_gb:
        # Convert GB to bytes
        max_size_bytes = int(args.max_size_gb * 1024 * 1024 * 1024)
    elif args.max_size:
        max_size_bytes = parse_size(args.max_size)
    
    max_count = args.keep
    
    # Validation
    if not any([max_days is not None, max_size_bytes is not None, max_count is not None]):
        print("[ERROR] At least one of --days/--keep-days, --max-size/--max-size-gb, or --keep required", file=sys.stderr)
        return 1
    
    print("\n" + "="*60)
    print("ARTIFACT ROTATION" + (" (DRY RUN)" if args.dry_run else ""))
    print("="*60 + "\n")
    
    # Scan files from all roots
    all_files = []
    for scan_dir in scan_dirs:
        print(f"[SCAN] Scanning {scan_dir}/...")
        files = scan_artifacts(scan_dir)
        all_files.extend(files)
    
    total_size = sum(f[2] for f in all_files)
    print(f"[SCAN] Found {len(all_files)} files ({format_size(total_size)} total)\n")
    
    # Apply filters
    to_delete = set()
    
    if max_days is not None:
        print(f"[TTL] Applying TTL filter (>{max_days} days)...")
        ttl_delete = apply_ttl_filter(all_files, max_days)
        to_delete.update(ttl_delete)
        print(f"[TTL] Marked {len(ttl_delete)} files for deletion\n")
    
    if max_size_bytes is not None:
        print(f"[SIZE] Applying size filter (max {format_size(max_size_bytes)})...")
        size_delete = apply_size_filter(all_files, max_size_bytes)
        to_delete.update(size_delete)
        print(f"[SIZE] Marked {len(size_delete)} files for deletion\n")
    
    if max_count is not None:
        print(f"[COUNT] Applying count filter (keep {max_count} newest)...")
        count_delete = apply_count_filter(all_files, max_count)
        to_delete.update(count_delete)
        print(f"[COUNT] Marked {len(count_delete)} files for deletion\n")
    
    # Execute deletion
    if not to_delete:
        print("[OK] No files to delete\n")
        # Final marker
        rotation_mode = "DRYRUN" if args.dry_run else "REAL"
        print(f"| rotate_artifacts | OK | ROTATION={rotation_mode} |\n")
        return 0
    
    print(f"[ACTION] {len(to_delete)} files to process:")
    deleted_size = 0
    deleted_count = 0
    archive_path = None
    
    # Archive if requested
    if args.archive_dir and to_delete:
        print(f"\n[ARCHIVE] Creating archive...")
        if not args.dry_run:
            try:
                archive_path = create_archive(list(to_delete), args.archive_dir, dry_run=False)
                print(f"[ARCHIVE] Created: {archive_path}")
            except Exception as e:
                print(f"[ERROR] Failed to create archive: {e}", file=sys.stderr)
                return 1
        else:
            archive_path = create_archive(list(to_delete), args.archive_dir, dry_run=True)
            print(f"[ARCHIVE] Would create: {archive_path}")
        print()
    
    # List files
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
    
    # Summary
    total_size_to_delete = sum(f[2] for f in all_files if f[0] in to_delete)
    
    if args.dry_run:
        print(f"[DRY RUN] Would delete {len(to_delete)} files ({format_size(total_size_to_delete)})")
        if archive_path:
            print(f"[DRY RUN] Would archive to: {archive_path}")
    else:
        print(f"[DONE] Deleted {deleted_count} files ({format_size(deleted_size)})")
        if archive_path:
            print(f"[DONE] Archived to: {archive_path}")
    
    # Final marker
    rotation_mode = "DRYRUN" if args.dry_run else "REAL"
    print(f"\n| rotate_artifacts | OK | ROTATION={rotation_mode} |\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

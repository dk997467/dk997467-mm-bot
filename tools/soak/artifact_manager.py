#!/usr/bin/env python3
"""
Artifact Lifecycle Manager for Soak Tests.

Automatically rotates old ITER_SUMMARY files, compresses old snapshots,
and monitors disk usage to prevent storage bloat.

Usage:
    python -m tools.soak.artifact_manager --path artifacts/soak --ttl-days 7 --max-size-mb 900 --keep-latest 100

Features:
    - Remove old ITER_SUMMARY_*.json (keep N latest)
    - Compress snapshots older than TTL days to .tar.gz
    - Monitor and report disk usage
    - Deterministic JSONL logging
"""

import argparse
import json
import tarfile
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional


def get_directory_size_mb(path: Path) -> float:
    """Calculate total size of directory in MB."""
    total_size = 0
    try:
        for entry in path.rglob('*'):
            if entry.is_file():
                total_size += entry.stat().st_size
    except Exception as e:
        print(f"[WARN] Error calculating directory size: {e}")
    return total_size / (1024 * 1024)


def rotate_iter_summaries(base_path: Path, keep_latest: int) -> Dict[str, Any]:
    """
    Remove old ITER_SUMMARY files, keeping only the N most recent.
    
    Args:
        base_path: Base directory (e.g., artifacts/soak)
        keep_latest: Number of recent files to keep
    
    Returns:
        Dict with rotation stats
    """
    latest_dir = base_path / "latest"
    if not latest_dir.exists():
        return {"deleted": 0, "kept": 0, "files": []}
    
    # Find all ITER_SUMMARY files
    iter_files = sorted(
        latest_dir.glob("ITER_SUMMARY_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True  # Newest first
    )
    
    deleted_files = []
    deleted_count = 0
    
    # Delete old files (beyond keep_latest)
    for old_file in iter_files[keep_latest:]:
        try:
            file_size_kb = old_file.stat().st_size / 1024
            old_file.unlink()
            deleted_files.append(old_file.name)
            deleted_count += 1
            print(f"| cleanup | REMOVED | {old_file.name} ({file_size_kb:.1f} KB) |")
        except Exception as e:
            print(f"[WARN] Could not delete {old_file.name}: {e}")
    
    return {
        "deleted": deleted_count,
        "kept": min(len(iter_files), keep_latest),
        "files": sorted(deleted_files)  # Sorted for determinism
    }


def compress_old_snapshots(base_path: Path, ttl_days: int) -> Dict[str, Any]:
    """
    Compress snapshots older than TTL days to .tar.gz.
    
    Args:
        base_path: Base directory (e.g., artifacts/soak)
        ttl_days: Age threshold in days
    
    Returns:
        Dict with compression stats
    """
    snapshots_dir = base_path / "snapshots"
    if not snapshots_dir.exists():
        return {"compressed": 0, "total_reduction_kb": 0, "files": []}
    
    cutoff = datetime.now() - timedelta(days=ttl_days)
    compressed_files = []
    compressed_count = 0
    total_reduction_kb = 0
    
    for snapshot in snapshots_dir.glob("*.json"):
        try:
            mtime = datetime.fromtimestamp(snapshot.stat().st_mtime)
            
            if mtime < cutoff:
                tar_path = snapshot.with_suffix('.json.tar.gz')
                
                # Skip if already compressed
                if tar_path.exists():
                    print(f"| cleanup | SKIP | {snapshot.name} (already compressed) |")
                    continue
                
                original_size_kb = snapshot.stat().st_size / 1024
                
                # Create compressed archive
                with tarfile.open(tar_path, 'w:gz') as tar:
                    tar.add(snapshot, arcname=snapshot.name)
                
                compressed_size_kb = tar_path.stat().st_size / 1024
                reduction_kb = original_size_kb - compressed_size_kb
                compression_ratio = (reduction_kb / original_size_kb * 100) if original_size_kb > 0 else 0
                
                # Remove original
                snapshot.unlink()
                
                compressed_files.append({
                    "file": snapshot.name,
                    "original_kb": round(original_size_kb, 2),
                    "compressed_kb": round(compressed_size_kb, 2),
                    "reduction_kb": round(reduction_kb, 2),
                    "ratio_pct": round(compression_ratio, 1)
                })
                compressed_count += 1
                total_reduction_kb += reduction_kb
                
                print(f"| cleanup | COMPRESSED | {snapshot.name} -> {tar_path.name} "
                      f"({original_size_kb:.1f}KB -> {compressed_size_kb:.1f}KB, "
                      f"{compression_ratio:.0f}% reduction) |")
        
        except Exception as e:
            print(f"[WARN] Could not compress {snapshot.name}: {e}")
    
    return {
        "compressed": compressed_count,
        "total_reduction_kb": round(total_reduction_kb, 2),
        "files": compressed_files  # Already deterministic (sorted by glob)
    }


def check_disk_usage(base_path: Path, max_size_mb: Optional[int] = None) -> Dict[str, Any]:
    """
    Check total disk usage and warn if exceeds limit.
    
    Args:
        base_path: Base directory to measure
        max_size_mb: Optional size limit (MB)
    
    Returns:
        Dict with disk usage stats
    """
    if not base_path.exists():
        return {"size_mb": 0, "within_limit": True, "warning": "Directory does not exist"}
    
    size_mb = get_directory_size_mb(base_path)
    within_limit = True
    warning = None
    
    if max_size_mb and size_mb > max_size_mb:
        within_limit = False
        warning = f"Size {size_mb:.1f}MB exceeds limit {max_size_mb}MB"
        print(f"| cleanup | WARN | {warning} |")
    else:
        print(f"| cleanup | OK | size={size_mb:.1f}MB" +
              (f" (limit: {max_size_mb}MB)" if max_size_mb else "") + " |")
    
    return {
        "size_mb": round(size_mb, 2),
        "limit_mb": max_size_mb,
        "within_limit": within_limit,
        "warning": warning
    }


def write_rotation_log(base_path: Path, report: Dict[str, Any]):
    """
    Write rotation log to JSONL file.
    
    Args:
        base_path: Base directory
        report: Rotation report to log
    """
    log_dir = base_path / "rotation"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_path = log_dir / "ROTATION_LOG.jsonl"
    
    # Deterministic JSON: sort keys, no ensure_ascii (but we'll use ASCII-safe data)
    log_entry = json.dumps(report, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    
    try:
        with open(log_path, 'a', encoding='ascii') as f:
            f.write(log_entry + '\n')
        print(f"| cleanup | LOG | Written to {log_path} |")
    except Exception as e:
        print(f"[WARN] Could not write rotation log: {e}")


def generate_rotation_report(
    base_path: Path,
    rotation_stats: Dict[str, Any],
    compression_stats: Dict[str, Any],
    disk_stats: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate comprehensive rotation report.
    
    Returns:
        Deterministic JSON report
    """
    return {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_path": str(base_path),
        "rotation": rotation_stats,
        "compression": compression_stats,
        "disk_usage": disk_stats,
        "summary": {
            "deleted_files": rotation_stats["deleted"],
            "compressed_snapshots": compression_stats["compressed"],
            "disk_reduction_kb": compression_stats["total_reduction_kb"],
            "final_size_mb": disk_stats["size_mb"],
            "within_limit": disk_stats["within_limit"]
        }
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Manage soak test artifacts lifecycle",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Rotate with defaults
  python -m tools.soak.artifact_manager --path artifacts/soak

  # Custom retention and limits
  python -m tools.soak.artifact_manager \\
    --path artifacts/soak \\
    --ttl-days 7 \\
    --max-size-mb 900 \\
    --keep-latest 100

  # Dry-run mode (report only, no changes)
  python -m tools.soak.artifact_manager --path artifacts/soak --dry-run
        """
    )
    
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Base path to manage (e.g., artifacts/soak)"
    )
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=7,
        help="Compress snapshots older than N days (default: 7)"
    )
    parser.add_argument(
        "--max-size-mb",
        type=int,
        default=None,
        help="Warn if total size exceeds N MB (default: no limit)"
    )
    parser.add_argument(
        "--keep-latest",
        type=int,
        default=100,
        help="Keep N most recent ITER_SUMMARY files (default: 100)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report only, do not delete or compress files"
    )
    
    args = parser.parse_args(argv)
    
    print("=" * 60)
    print("ARTIFACT LIFECYCLE MANAGER")
    print("=" * 60)
    print(f"Base path: {args.path}")
    print(f"TTL days: {args.ttl_days}")
    print(f"Max size: {args.max_size_mb or 'unlimited'} MB")
    print(f"Keep latest: {args.keep_latest} ITER_SUMMARY files")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)
    print()
    
    if not args.path.exists():
        print(f"[ERROR] Path does not exist: {args.path}")
        return 1
    
    # Measure initial size
    size_before_mb = get_directory_size_mb(args.path)
    print(f"| cleanup | START | size_before={size_before_mb:.2f}MB |")
    print()
    
    if args.dry_run:
        print("[DRY-RUN] Skipping actual cleanup operations")
        rotation_stats = {"deleted": 0, "kept": 0, "files": []}
        compression_stats = {"compressed": 0, "total_reduction_kb": 0, "files": []}
    else:
        # 1. Rotate ITER_SUMMARY files
        print("--- Rotating ITER_SUMMARY files ---")
        rotation_stats = rotate_iter_summaries(args.path, args.keep_latest)
        print(f"| cleanup | ROTATION | deleted={rotation_stats['deleted']} kept={rotation_stats['kept']} |")
        print()
        
        # 2. Compress old snapshots
        print("--- Compressing old snapshots ---")
        compression_stats = compress_old_snapshots(args.path, args.ttl_days)
        print(f"| cleanup | COMPRESSION | compressed={compression_stats['compressed']} "
              f"saved={compression_stats['total_reduction_kb']:.1f}KB |")
        print()
    
    # 3. Check disk usage
    print("--- Checking disk usage ---")
    disk_stats = check_disk_usage(args.path, args.max_size_mb)
    
    # Measure final size
    size_after_mb = get_directory_size_mb(args.path)
    size_reduction_mb = size_before_mb - size_after_mb
    
    print()
    print("=" * 60)
    print("ROTATION COMPLETE")
    print("=" * 60)
    print(f"Size before: {size_before_mb:.2f} MB")
    print(f"Size after:  {size_after_mb:.2f} MB")
    print(f"Reduction:   {size_reduction_mb:.2f} MB ({size_reduction_mb/size_before_mb*100:.1f}%)" 
          if size_before_mb > 0 else "Reduction:   0 MB")
    print(f"Files deleted: {rotation_stats['deleted']}")
    print(f"Snapshots compressed: {compression_stats['compressed']}")
    print("=" * 60)
    
    # Generate and write report
    report = generate_rotation_report(
        args.path,
        rotation_stats,
        compression_stats,
        disk_stats
    )
    
    if not args.dry_run:
        write_rotation_log(args.path, report)
    
    # Exit code: 0 = OK, 1 = error, 2 = warning (size exceeded)
    if not disk_stats["within_limit"]:
        return 2
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())


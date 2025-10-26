#!/usr/bin/env python3
"""
Artifact dump utility: Create index of all artifacts for debugging.

Usage:
    python -m tools.audit.dump \\
        --base artifacts \\
        --out artifacts/audit/DUMP_INDEX.json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict


def collect_artifacts(base_dir: Path) -> List[Dict[str, any]]:
    """
    Collect all artifacts from base directory.
    
    Args:
        base_dir: Base directory to scan
    
    Returns:
        List of artifact metadata dicts
    """
    artifacts = []
    
    if not base_dir.exists():
        return artifacts
    
    for path in base_dir.rglob("*"):
        if path.is_file():
            try:
                stat = path.stat()
                artifacts.append({
                    "path": str(path.relative_to(base_dir)),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "type": path.suffix or "unknown"
                })
            except Exception as e:
                print(f"[WARN] Failed to stat {path}: {e}", file=sys.stderr)
    
    return artifacts


def main(argv=None) -> int:
    """
    Main entry point for artifact dump.
    
    Returns:
        0 on success, 1 on failure
    """
    parser = argparse.ArgumentParser(description="Dump artifact index for debugging")
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("artifacts"),
        help="Base directory to scan (default: artifacts)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/audit/DUMP_INDEX.json"),
        help="Output file"
    )
    
    args = parser.parse_args(argv)
    
    print(f"Scanning artifacts in: {args.base}")
    
    # Collect artifacts
    artifacts = collect_artifacts(args.base)
    
    # Build index
    index = {
        "status": "OK",
        "base_dir": str(args.base),
        "artifact_count": len(artifacts),
        "artifacts": artifacts
    }
    
    # Ensure output directory exists
    args.out.parent.mkdir(parents=True, exist_ok=True)
    
    # Write index
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    
    print(f"[OK] Collected {len(artifacts)} artifacts")
    print(f"  Index written to: {args.out}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())


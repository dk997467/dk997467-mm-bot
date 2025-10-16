#!/usr/bin/env python3
"""
Freeze configuration snapshot tool.

Usage:
    python -m tools.freeze_config --source artifacts/soak/runtime_overrides.json --label "steady_safe_2025Q4"

Creates a timestamped snapshot of stable configuration for production use.
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def create_freeze_snapshot(source_path: str, label: str) -> None:
    """
    Create a frozen snapshot of configuration.
    
    Args:
        source_path: Path to source config file (e.g., runtime_overrides.json)
        label: Human-readable label for the snapshot
    """
    source = Path(source_path)
    
    if not source.exists():
        print(f"[ERROR] Source file not found: {source_path}")
        return 1
    
    # Load source config
    with open(source, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Create snapshot directory
    snapshots_dir = Path("artifacts/soak/snapshots")
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate snapshot filename with timestamp
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    snapshot_filename = f"freeze_{label}_{timestamp}.json"
    snapshot_path = snapshots_dir / snapshot_filename
    
    # Add metadata to snapshot
    snapshot_data = {
        "metadata": {
            "label": label,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "source": str(source),
            "version": "1.0"
        },
        "config": config
    }
    
    # Save snapshot
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot_data, f, indent=2)
    
    print(f"[OK] Freeze snapshot created")
    print(f"  Label: {label}")
    print(f"  Path: {snapshot_path}")
    print(f"  Timestamp: {snapshot_data['metadata']['created_at']}")
    print()
    print("Snapshot config:")
    for param, value in sorted(config.items()):
        if isinstance(value, float):
            print(f"  {param:30s} = {value:.2f}")
        else:
            print(f"  {param:30s} = {value}")
    
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create freeze snapshot of stable config")
    parser.add_argument("--source", required=True, help="Source config file path")
    parser.add_argument("--label", required=True, help="Snapshot label (e.g., 'steady_safe_2025Q4')")
    args = parser.parse_args(argv)
    
    return create_freeze_snapshot(args.source, args.label)


if __name__ == "__main__":
    exit(main())


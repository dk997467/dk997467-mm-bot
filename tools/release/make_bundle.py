#!/usr/bin/env python3
"""
Release Bundle Creator

Creates a release ZIP with VERSION, deploy configs, docs, and manifests.

Usage:
    python -m tools.release.make_bundle
"""

import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def read_version() -> str:
    """Read version from VERSION file."""
    version_file = Path("VERSION")
    if version_file.exists():
        return version_file.read_text().strip()
    return "0.1.0"


def collect_files() -> List[Dict[str, str]]:
    """
    Collect files for release bundle.
    
    Returns list of dicts with path, dest, and description.
    """
    files = []
    
    # Core files
    if Path("VERSION").exists():
        files.append({"path": "VERSION", "dest": "VERSION", "desc": "Version file"})
    
    if Path("README.md").exists():
        files.append({"path": "README.md", "dest": "README.md", "desc": "Main README"})
    
    if Path("CHANGELOG.md").exists():
        files.append({"path": "CHANGELOG.md", "dest": "CHANGELOG.md", "desc": "Changelog"})
    
    # Deploy configs
    deploy_patterns = [
        "deploy/prometheus/alerts_soak.yml",
        "deploy/policies/rollback.yaml",
        "deploy/grafana/dashboards/mm_operability.json"
    ]
    
    for pattern in deploy_patterns:
        path = Path(pattern)
        if path.exists():
            files.append({"path": str(path), "dest": str(path), "desc": f"Deploy config: {path.name}"})
    
    # Optional: recent reports (if they exist)
    report_patterns = [
        "artifacts/reports/SOAK_RESULTS.md",
        "artifacts/reports/soak_metrics.json",
        "artifacts/reports/readiness.json"
    ]
    
    for pattern in report_patterns:
        path = Path(pattern)
        if path.exists():
            files.append({"path": str(path), "dest": f"reports/{path.name}", "desc": f"Report: {path.name}"})
    
    return files


def create_manifest(files: List[Dict[str, str]], version: str) -> Dict[str, Any]:
    """Create manifest with SHA256 hashes."""
    manifest = {
        "version": version,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": []
    }
    
    for file_info in files:
        path = Path(file_info["path"])
        if path.exists():
            manifest["files"].append({
                "path": file_info["dest"],
                "sha256": calculate_sha256(path),
                "size": path.stat().st_size,
                "description": file_info["desc"]
            })
    
    return manifest


def create_bundle(output_path: str) -> int:
    """Create release bundle ZIP."""
    version = read_version()
    
    print("\n" + "="*60)
    print(f"CREATING RELEASE BUNDLE (v{version})")
    print("="*60 + "\n")
    
    # Collect files
    print("[1/4] Collecting files...")
    files = collect_files()
    print(f"       Found {len(files)} files\n")
    
    # Create manifest
    print("[2/4] Creating manifest...")
    manifest = create_manifest(files, version)
    print(f"       Generated manifest with {len(manifest['files'])} entries\n")
    
    # Create ZIP
    print("[3/4] Creating ZIP archive...")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add collected files
        for file_info in files:
            path = Path(file_info["path"])
            if path.exists():
                zf.write(path, file_info["dest"])
                print(f"       + {file_info['dest']}")
        
        # Add manifest
        manifest_json = json.dumps(manifest, indent=2, sort_keys=True)
        zf.writestr("MANIFEST.json", manifest_json)
        print(f"       + MANIFEST.json")
    
    print()
    
    # Calculate bundle hash
    print("[4/4] Calculating bundle SHA256...")
    bundle_hash = calculate_sha256(Path(output_path))
    bundle_size = Path(output_path).stat().st_size
    
    print(f"       SHA256: {bundle_hash}")
    print(f"       Size: {bundle_size:,} bytes\n")
    
    # Write hash file
    hash_file = output_path + ".sha256"
    with open(hash_file, 'w') as f:
        f.write(f"{bundle_hash}  {Path(output_path).name}\n")
    
    print("-"*60)
    print(f"Bundle: {output_path}")
    print(f"Hash:   {hash_file}")
    print("-"*60 + "\n")
    
    return 0


def main() -> int:
    """Main entry point."""
    version = read_version()
    output_path = f"artifacts/release/mm-bot-v{version}.zip"
    
    return create_bundle(output_path)


if __name__ == "__main__":
    sys.exit(main())

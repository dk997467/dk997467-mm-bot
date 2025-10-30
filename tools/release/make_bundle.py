#!/usr/bin/env python3
"""
Release Bundle Creator

Creates a release ZIP with VERSION, deploy configs, docs, and manifests.

Usage:
    python -m tools.release.make_bundle
    
    # With environment variables for determinism:
    MM_VERSION=test-1.0.0 MM_FREEZE_UTC_ISO=2025-01-01T00:00:00Z \
        python -m tools.release.make_bundle
"""

import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def read_version() -> str:
    """Read version from MM_VERSION env var or VERSION file."""
    # Priority: MM_VERSION env var > VERSION file > default
    if 'MM_VERSION' in os.environ:
        return os.environ['MM_VERSION']
    
    version_file = Path("VERSION")
    if version_file.exists():
        return version_file.read_text().strip()
    
    return "0.1.0"


def get_utc_timestamp() -> str:
    """Get UTC timestamp, respecting MM_FREEZE_UTC_ISO for determinism."""
    if 'MM_FREEZE_UTC_ISO' in os.environ:
        return os.environ['MM_FREEZE_UTC_ISO']
    
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
            # Normalize to forward slashes for cross-platform consistency
            dest_path = str(path).replace('\\', '/')
            files.append({"path": str(path), "dest": dest_path, "desc": f"Deploy config: {path.name}"})
    
    # Optional: recent reports (if they exist)
    report_patterns = [
        "artifacts/reports/SOAK_RESULTS.md",
        "artifacts/reports/soak_metrics.json",
        "artifacts/reports/readiness.json"
    ]
    
    for pattern in report_patterns:
        path = Path(pattern)
        if path.exists():
            # Normalize to forward slashes for cross-platform consistency
            dest_path = f"reports/{path.name}".replace('\\', '/')
            files.append({"path": str(path), "dest": dest_path, "desc": f"Report: {path.name}"})
    
    return files


def _now_utc_z() -> str:
    """Get current UTC timestamp in ISO 8601 format with Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def create_manifest(files: List[Dict[str, str]], version: str, utc: Optional[str] = None) -> Dict[str, Any]:
    """
    Create manifest with SHA256 hashes.
    
    Args:
        files: List of file dictionaries with path, dest, and desc
        version: Version string for the bundle
        utc: Optional UTC timestamp. If None, uses current UTC time with Z suffix
    
    Returns:
        Manifest dictionary with bundle metadata and file entries
    """
    if utc is None:
        utc = _now_utc_z()
    
    manifest: Dict[str, Any] = {
        "bundle": {
            "version": version,
            "utc": utc
        },
        "result": "READY",  # Can be READY or PARTIAL
        "files": []
    }
    
    # Sort files by path for deterministic ordering
    sorted_files = sorted(files, key=lambda f: f["dest"])
    
    for file_info in sorted_files:
        path = Path(file_info["path"])
        if path.exists():
            manifest["files"].append({
                "path": file_info["dest"],
                "sha256": calculate_sha256(path),
                "size": path.stat().st_size,
                "description": file_info["desc"]
            })
    
    # Set result based on file collection
    if not manifest["files"]:
        manifest["result"] = "PARTIAL"
    
    return manifest


def create_bundle() -> int:
    """Create release bundle ZIP."""
    version = read_version()
    utc = get_utc_timestamp()
    
    print("\n" + "="*60)
    print(f"CREATING RELEASE BUNDLE (v{version})")
    print("="*60 + "\n")
    
    # Collect files
    print("[1/5] Collecting files...")
    files = collect_files()
    print(f"       Found {len(files)} files\n")
    
    # Create manifest
    print("[2/5] Creating manifest...")
    manifest = create_manifest(files, version, utc)
    print(f"       Generated manifest with {len(manifest['files'])} entries\n")
    
    # Write manifest to artifacts/
    print("[3/5] Writing manifest...")
    manifest_path = Path("artifacts/RELEASE_BUNDLE_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(manifest_path, 'w', encoding='ascii') as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    
    print(f"       Manifest: {manifest_path}\n")
    
    # Create ZIP with deterministic filename
    print("[4/5] Creating ZIP archive...")
    
    # Bundle filename: {safe_utc}-mm-bot.zip
    safe_utc = utc.replace(':', '')
    bundle_dir = Path("dist/release_bundle")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{safe_utc}-mm-bot.zip"
    
    # Sort files by dest path for deterministic zip ordering
    sorted_files = sorted(files, key=lambda f: f["dest"])
    
    with zipfile.ZipFile(bundle_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add files in sorted order to match manifest
        for file_entry in manifest["files"]:
            # Find original file info
            orig_file = next((f for f in files if f["dest"] == file_entry["path"]), None)
            if orig_file:
                path = Path(orig_file["path"])
                if path.exists():
                    zf.write(path, file_entry["path"])
                    print(f"       + {file_entry['path']}")
    
    print()
    
    # Calculate bundle hash
    print("[5/5] Calculating bundle SHA256...")
    bundle_hash = calculate_sha256(bundle_path)
    bundle_size = bundle_path.stat().st_size
    
    print(f"       SHA256: {bundle_hash}")
    print(f"       Size: {bundle_size:,} bytes\n")
    
    # Write hash file
    hash_file = str(bundle_path) + ".sha256"
    with open(hash_file, 'w') as f:
        f.write(f"{bundle_hash}  {bundle_path.name}\n")
    
    print("-"*60)
    print(f"Bundle: {bundle_path}")
    print(f"Hash:   {hash_file}")
    print(f"Manifest: {manifest_path}")
    print("-"*60)
    
    # Final marker for CI/CD parsing
    print(f"\n| release_bundle | OK | RELEASE_BUNDLE={bundle_path} |\n")
    
    return 0


def main() -> int:
    """Main entry point."""
    try:
        return create_bundle()
    except Exception as e:
        print(f"[ERROR] Failed to create release bundle: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

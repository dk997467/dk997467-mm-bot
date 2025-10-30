"""
Unit tests for release bundle maker.
"""

import sys
sys.path.insert(0, ".")

import json
import tempfile
import zipfile
from pathlib import Path

from tools.release.make_bundle import calculate_sha256, read_version, create_manifest


def test_calculate_sha256():
    """Test SHA256 calculation."""
    with tempfile.NamedTemporaryFile(delete=False, mode='w') as tmp:
        tmp.write("test content")
        tmp_path = tmp.name
    
    try:
        hash1 = calculate_sha256(Path(tmp_path))
        hash2 = calculate_sha256(Path(tmp_path))
        
        # Same file should give same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 is 64 hex chars
    finally:
        Path(tmp_path).unlink()
    
    print("✓ SHA256 calculation test passed")


def test_read_version():
    """Test version reading."""
    # Should return a version string (either from file or default)
    version = read_version()
    assert isinstance(version, str)
    assert len(version) > 0
    
    print("✓ Version reading test passed")


def test_create_manifest():
    """Test manifest creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test file
        test_file = Path(tmpdir) / "test.txt"
        test_file.write_text("test content")
        
        files = [{
            "path": str(test_file),
            "dest": "test.txt",
            "desc": "Test file"
        }]
        
        # Test without explicit UTC (uses default)
        manifest = create_manifest(files, "1.0.0")
        
        assert manifest["bundle"]["version"] == "1.0.0"
        assert "utc" in manifest["bundle"]
        assert manifest["bundle"]["utc"].endswith("Z")  # ISO format with Z suffix
        assert manifest["result"] in ("READY", "PARTIAL")
        assert len(manifest["files"]) == 1
        assert manifest["files"][0]["path"] == "test.txt"
        assert "sha256" in manifest["files"][0]
        assert manifest["files"][0]["size"] > 0
        
        # Test with explicit UTC
        manifest2 = create_manifest(files, "2.0.0", "2025-01-01T00:00:00Z")
        assert manifest2["bundle"]["version"] == "2.0.0"
        assert manifest2["bundle"]["utc"] == "2025-01-01T00:00:00Z"
    
    print("✓ Manifest creation test passed")


if __name__ == "__main__":
    test_calculate_sha256()
    test_read_version()
    test_create_manifest()
    print("\n✓ All make_bundle tests passed")


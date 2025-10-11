"""
Unit tests for rotate_artifacts CLI.
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path


def test_rotate_dryrun():
    """Test rotate_artifacts in dry-run mode with old-style flags."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test directory structure
        artifacts_dir = Path(tmpdir) / "artifacts"
        artifacts_dir.mkdir()
        
        # Create test files
        for i in range(5):
            test_file = artifacts_dir / f"test_{i}.txt"
            test_file.write_text(f"test content {i}")
            time.sleep(0.01)  # Ensure different timestamps
        
        # Run with old-style flags
        result = subprocess.run(
            [
                sys.executable, "-m", "tools.ops.rotate_artifacts",
                "--roots", str(artifacts_dir),
                "--keep-days", "0",  # All files are "old"
                "--dry-run"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        print(f"Exit code: {result.returncode}")
        print(f"Stdout:\n{result.stdout}")
        print(f"Stderr:\n{result.stderr}")
        
        # Should succeed with exit 0
        assert result.returncode == 0, \
            f"Expected exit 0, got {result.returncode}\nStderr: {result.stderr}"
        
        # Should have marker
        assert "| rotate_artifacts | OK | ROTATION=DRYRUN |" in result.stdout, \
            f"Expected DRYRUN marker in output:\n{result.stdout}"
        
        # Files should still exist (dry-run)
        assert len(list(artifacts_dir.glob("*.txt"))) == 5, \
            "Files should not be deleted in dry-run mode"
        
        print("✓ Dry-run test passed")


def test_rotate_with_max_size_gb():
    """Test rotate_artifacts with --max-size-gb flag."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = Path(tmpdir) / "artifacts"
        artifacts_dir.mkdir()
        
        # Create test file
        test_file = artifacts_dir / "large.txt"
        test_file.write_text("x" * 1000)  # 1KB file
        
        # Run with max-size-gb (very small to trigger cleanup)
        result = subprocess.run(
            [
                sys.executable, "-m", "tools.ops.rotate_artifacts",
                "--roots", str(artifacts_dir),
                "--max-size-gb", "0.000001",  # ~1KB (will trigger)
                "--dry-run"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}"
        assert "| rotate_artifacts | OK | ROTATION=DRYRUN |" in result.stdout
        
        print("✓ Max-size-gb test passed")


def test_rotate_multiple_roots():
    """Test rotate_artifacts with multiple --roots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create multiple directories
        dir1 = Path(tmpdir) / "artifacts1"
        dir2 = Path(tmpdir) / "artifacts2"
        dir1.mkdir()
        dir2.mkdir()
        
        # Create files in both
        (dir1 / "test1.txt").write_text("test1")
        (dir2 / "test2.txt").write_text("test2")
        
        # Run with multiple roots
        result = subprocess.run(
            [
                sys.executable, "-m", "tools.ops.rotate_artifacts",
                "--roots", str(dir1), str(dir2),
                "--keep-days", "0",
                "--dry-run"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}"
        assert "Found 2 files" in result.stdout, "Should find files from both roots"
        
        print("✓ Multiple roots test passed")


if __name__ == "__main__":
    print("\n[UNIT TESTS] Running rotate_artifacts unit tests\n")
    test_rotate_dryrun()
    test_rotate_with_max_size_gb()
    test_rotate_multiple_roots()
    print("\n✓ All rotate_artifacts unit tests passed\n")


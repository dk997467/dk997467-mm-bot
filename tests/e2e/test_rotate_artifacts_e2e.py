"""
E2E tests for rotate_artifacts with real deletion and archiving.
"""

import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path


def test_rotate_real():
    """Test rotate_artifacts in real mode with archiving."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test directory structure
        artifacts_dir = Path(tmpdir) / "artifacts"
        archive_dir = Path(tmpdir) / "archives"
        artifacts_dir.mkdir()
        archive_dir.mkdir()
        
        # Create test files with different ages
        old_file = artifacts_dir / "old.txt"
        new_file = artifacts_dir / "new.txt"
        
        old_file.write_text("old content")
        time.sleep(0.1)
        new_file.write_text("new content")
        
        # Run with real mode and archiving
        result = subprocess.run(
            [
                sys.executable, "-m", "tools.ops.rotate_artifacts",
                "--roots", str(artifacts_dir),
                "--keep", "1",  # Keep only 1 newest file
                "--archive-dir", str(archive_dir)
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
        
        # Should have REAL marker
        assert "| rotate_artifacts | OK | ROTATION=REAL |" in result.stdout, \
            f"Expected REAL marker in output:\n{result.stdout}"
        
        # Old file should be deleted
        assert not old_file.exists(), "Old file should be deleted"
        
        # New file should remain
        assert new_file.exists(), "New file should remain"
        
        # Archive should be created
        archives = list(archive_dir.glob("*.zip"))
        assert len(archives) == 1, f"Expected 1 archive, found {len(archives)}"
        
        # Verify archive contains the deleted file
        with zipfile.ZipFile(archives[0], 'r') as zf:
            archived_files = zf.namelist()
            assert any("old.txt" in name for name in archived_files), \
                f"Archive should contain old.txt, got: {archived_files}"
        
        print("✓ Real mode test passed")


def test_rotate_real_without_archive():
    """Test rotate_artifacts in real mode without archiving."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = Path(tmpdir) / "artifacts"
        artifacts_dir.mkdir()
        
        # Create test files
        for i in range(3):
            (artifacts_dir / f"test_{i}.txt").write_text(f"test {i}")
        
        # Run with real mode, no archiving
        result = subprocess.run(
            [
                sys.executable, "-m", "tools.ops.rotate_artifacts",
                "--roots", str(artifacts_dir),
                "--keep", "1"  # Keep only 1 newest
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}"
        assert "| rotate_artifacts | OK | ROTATION=REAL |" in result.stdout
        
        # Should have only 1 file left
        remaining = list(artifacts_dir.glob("*.txt"))
        assert len(remaining) == 1, f"Expected 1 file, found {len(remaining)}"
        
        print("✓ Real mode without archive test passed")


def test_rotate_no_files_to_delete():
    """Test rotate_artifacts when no files match deletion criteria."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = Path(tmpdir) / "artifacts"
        artifacts_dir.mkdir()
        
        # Create one test file
        (artifacts_dir / "test.txt").write_text("test")
        
        # Run with criteria that won't match
        result = subprocess.run(
            [
                sys.executable, "-m", "tools.ops.rotate_artifacts",
                "--roots", str(artifacts_dir),
                "--keep-days", "365",  # Very old
                "--dry-run"
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        assert result.returncode == 0, f"Expected exit 0, got {result.returncode}"
        assert "| rotate_artifacts | OK | ROTATION=DRYRUN |" in result.stdout
        assert "[OK] No files to delete" in result.stdout
        
        print("✓ No files to delete test passed")


if __name__ == "__main__":
    print("\n[E2E TESTS] Running rotate_artifacts E2E tests\n")
    test_rotate_real()
    test_rotate_real_without_archive()
    test_rotate_no_files_to_delete()
    print("\n✓ All rotate_artifacts E2E tests passed\n")

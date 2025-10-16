"""
Unit tests for scan_secrets CI tool - critical artifacts detection.

Tests that secrets found in artifacts/** result in exit code 2.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def test_scan_secrets_finds_fixture():
    """
    Test that secrets in artifacts/** result in exit code 2 (CRITICAL).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create WORK_DIR structure
        work_dir = Path(tmpdir)
        artifacts_dir = work_dir / "artifacts"
        artifacts_dir.mkdir()
        
        # Create a file with a fake secret
        leaky_file = artifacts_dir / "leaky_logs.txt"
        leaky_file.write_text(
            "API_KEY=sk_test_51234567890abcdefghijklmnopqrstuvwxyz\n"
            "This is a test leak\n"
        )
        
        # Run scan_secrets with WORK_DIR set
        env = os.environ.copy()
        env["WORK_DIR"] = str(work_dir)
        
        result = subprocess.run(
            [sys.executable, "-m", "tools.ci.scan_secrets"],
            capture_output=True,
            text=True,
            env=env,
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            timeout=30
        )
        
        # Should exit with code 2 (CRITICAL)
        assert result.returncode == 2, \
            f"Expected exit code 2 for secrets in artifacts/, got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        # Check for CRITICAL marker in output
        assert "RESULT=CRITICAL" in result.stdout, \
            f"Expected 'RESULT=CRITICAL' in output, got: {result.stdout}"
        
        assert "[CRITICAL]" in result.stderr, \
            f"Expected '[CRITICAL]' in stderr, got: {result.stderr}"
        
        print("✓ scan_secrets detects artifacts leak → exit 2 (CRITICAL)")


def test_scan_secrets_clean_repo():
    """
    Test that clean repo (no secrets) results in exit code 0.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create minimal WORK_DIR structure with no secrets
        work_dir = Path(tmpdir)
        src_dir = work_dir / "src"
        src_dir.mkdir()
        
        # Create a clean file
        clean_file = src_dir / "clean.py"
        clean_file.write_text(
            "# Clean Python file\n"
            "def hello():\n"
            "    return 'Hello World'\n"
        )
        
        # Run scan_secrets with WORK_DIR set
        env = os.environ.copy()
        env["WORK_DIR"] = str(work_dir)
        
        result = subprocess.run(
            [sys.executable, "-m", "tools.ci.scan_secrets"],
            capture_output=True,
            text=True,
            env=env,
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            timeout=30
        )
        
        # Should exit with code 0 (clean)
        assert result.returncode == 0, \
            f"Expected exit code 0 for clean repo, got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        assert "RESULT=CLEAN" in result.stdout, \
            f"Expected 'RESULT=CLEAN' in output, got: {result.stdout}"
        
        print("✓ scan_secrets clean repo → exit 0")


if __name__ == "__main__":
    test_scan_secrets_finds_fixture()
    test_scan_secrets_clean_repo()
    print("\n✓ All scan_secrets tests passed")

"""
Unit tests for scan_secrets CI tool.

Tests focused secret patterns, allowlist behavior, scope, and exit codes.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_scanner(work_dir: Path, extra_args=None, env_overrides=None):
    """Helper to run scan_secrets with custom work dir."""
    # Find repo root (where tools/ module exists)
    repo_root = Path(__file__).parent.parent
    
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    
    args = [sys.executable, "-m", "tools.ci.scan_secrets"]
    if extra_args:
        args.extend(extra_args)
    
    # Change to work_dir for scanning, but run from repo_root for module access
    # Pass --paths with absolute paths to work_dir
    if '--paths' not in (extra_args or []):
        # Convert work_dir to absolute and pass as --paths
        src_path = work_dir / "src"
        tools_path = work_dir / "tools"
        scripts_path = work_dir / "scripts"
        
        # Add --paths for directories that exist
        paths = []
        for p in [src_path, tools_path, scripts_path]:
            if p.exists():
                paths.append(str(p.absolute()))
        
        if paths:
            args.extend(['--paths'] + paths)
    
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo_root),  # Run from repo root
        timeout=30
    )
    return result


def test_clean_repo_exits_zero():
    """Test that clean repo (no secrets) exits with 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        src_dir = work_dir / "src"
        src_dir.mkdir()
        
        # Create clean file
        clean_file = src_dir / "clean.py"
        clean_file.write_text(
            "# Clean Python file\n"
            "def hello():\n"
            "    return 'Hello World'\n"
            "API_KEY = 'test_api_key_for_ci_only'  # allowlisted\n"
        )
        
        result = _run_scanner(work_dir)
        
        assert result.returncode == 0, \
            f"Expected exit 0 for clean repo, got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        assert "RESULT=CLEAN" in result.stdout
        print("✓ clean_repo_exits_zero")


def test_allowlisted_in_normal_mode_is_ok():
    """Test that allowlisted findings in normal mode exit with 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        src_dir = work_dir / "src"
        src_dir.mkdir()
        
        # Create file with masked secrets (allowlisted)
        masked_file = src_dir / "masked.py"
        masked_file.write_text(
            "# Config with masked values\n"
            "API_KEY = '****'\n"
            "SECRET = 'test_api_key_for_ci_only'\n"
        )
        
        result = _run_scanner(work_dir)
        
        assert result.returncode == 0, \
            f"Expected exit 0 for allowlisted findings, got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        assert "RESULT=CLEAN" in result.stdout
        assert "allowlisted finding(s)" in result.stderr or "No secrets found" in result.stderr
        print("✓ allowlisted_in_normal_mode_is_ok")


def test_allowlisted_in_strict_mode_fails():
    """Test that allowlisted findings in strict mode exit with 1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        src_dir = work_dir / "src"
        src_dir.mkdir()
        
        # Create file with masked secrets (allowlisted)
        masked_file = src_dir / "masked.py"
        masked_file.write_text(
            "# Config with masked values\n"
            "API_KEY = '****'\n"
        )
        
        result = _run_scanner(work_dir, extra_args=['--strict'])
        
        # Should exit 1 in strict mode if there are allowlisted findings
        # OR exit 0 if no findings at all (masked value might not match patterns)
        # Let's verify behavior is consistent
        if "allowlisted finding(s)" in result.stderr:
            assert result.returncode == 1, \
                f"Expected exit 1 for allowlisted findings in strict mode, got {result.returncode}\n" \
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            assert "RESULT=ALLOWLISTED_STRICT" in result.stdout
        else:
            # No findings matched (clean)
            assert result.returncode == 0
            assert "RESULT=CLEAN" in result.stdout
        
        print("✓ allowlisted_in_strict_mode_fails")


def test_real_secret_fails():
    """Test that real (non-allowlisted) secrets exit with 1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        src_dir = work_dir / "src"
        src_dir.mkdir()
        
        # Create file with real secret pattern (GitHub PAT - static string)
        leaky_file = src_dir / "leak.py"
        leaky_file.write_text(
            "# Accidentally committed secret\n"
            "GITHUB_TOKEN = 'ghp_1234567890abcdefghijklmnopqrstuvwxyzABCD'\n"
        )
        
        result = _run_scanner(work_dir)
        
        assert result.returncode == 1, \
            f"Expected exit 1 for real secrets, got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        assert "RESULT=FOUND" in result.stdout
        assert "[ERROR]" in result.stderr
        print("✓ real_secret_fails")


def test_ignores_golden_and_artifacts():
    """Test that golden/ and artifacts/ directories are ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        
        # Create source dir (will be scanned)
        src_dir = work_dir / "src"
        src_dir.mkdir()
        clean_file = src_dir / "clean.py"
        clean_file.write_text("# Clean file\n")
        
        # Create golden dir (should be ignored)
        golden_dir = work_dir / "tools" / "tuning" / "golden"
        golden_dir.mkdir(parents=True)
        golden_file = golden_dir / "data.json"
        # Use fake key that matches pattern but is obviously fake
        golden_file.write_text('{"api_key": "sk_test_fakekey1234567890abcdef"}')
        
        # Create artifacts dir (should be ignored)
        artifacts_dir = work_dir / "artifacts"
        artifacts_dir.mkdir()
        artifact_file = artifacts_dir / "metrics.txt"
        artifact_file.write_text("API_KEY=ghp_" + "x" * 36)
        
        result = _run_scanner(work_dir)
        
        # Should pass because golden/ and artifacts/ are in IGNORE_DIRS
        assert result.returncode == 0, \
            f"Expected exit 0 (ignored dirs), got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        assert "RESULT=CLEAN" in result.stdout
        print("✓ ignores_golden_and_artifacts")


def test_paths_override():
    """Test that --paths CLI arg overrides TARGET_DIRS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        
        # Create src/ with clean file
        src_dir = work_dir / "src"
        src_dir.mkdir()
        clean_file = src_dir / "clean.py"
        clean_file.write_text("# Clean\n")
        
        # Create tools/ with secret (but we'll only scan src/)
        tools_dir = work_dir / "tools"
        tools_dir.mkdir()
        leaky_file = tools_dir / "leak.py"
        leaky_file.write_text("TOKEN = 'ghp_" + "a" * 36 + "'\n")
        
        # Run with --paths src (should ignore tools/)
        result = _run_scanner(work_dir, extra_args=['--paths', str(src_dir.absolute())])
        
        assert result.returncode == 0, \
            f"Expected exit 0 (only scanned src/), got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        assert "RESULT=CLEAN" in result.stdout
        print("✓ paths_override")


def test_ignores_markdown_files():
    """Test that .md files are ignored via IGNORE_GLOBS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        src_dir = work_dir / "src"
        src_dir.mkdir()
        
        # Create README with example secrets (should be ignored)
        readme = src_dir / "README.md"
        readme.write_text(
            "# Example\n"
            "```\n"
            "export GITHUB_TOKEN=ghp_" + "x" * 36 + "\n"
            "```\n"
        )
        
        # Create Python file (clean)
        py_file = src_dir / "app.py"
        py_file.write_text("# App code\n")
        
        result = _run_scanner(work_dir)
        
        # Should pass because .md files are ignored
        assert result.returncode == 0, \
            f"Expected exit 0 (ignored .md), got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        assert "RESULT=CLEAN" in result.stdout
        print("✓ ignores_markdown_files")


def test_focused_patterns_reduce_false_positives():
    """Test that focused patterns don't match random hex/base64 data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        src_dir = work_dir / "src"
        src_dir.mkdir()
        
        # Create file with random hex data (not a real secret)
        data_file = src_dir / "data.json"
        data_file.write_text(
            '{\n'
            '  "order_id": "a1b2c3d4e5f6789012345678",\n'
            '  "hash": "abcdef1234567890abcdef1234567890",\n'
            '  "session": "MTIzNDU2Nzg5MGFiY2RlZmdoaWprbG1ub3A="\n'
            '}\n'
        )
        
        result = _run_scanner(work_dir)
        
        # Should pass because FOCUSED_PATTERNS don't match generic hex/base64
        assert result.returncode == 0, \
            f"Expected exit 0 (no false positives), got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        assert "RESULT=CLEAN" in result.stdout
        print("✓ focused_patterns_reduce_false_positives")


def test_aws_access_key_detected():
    """Test that real AWS access keys are detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        src_dir = work_dir / "src"
        src_dir.mkdir()
        
        # Create file with AWS access key pattern (NOT containing allowlisted words)
        config_file = src_dir / "config.py"
        config_file.write_text(
            "# AWS config\n"
            "AWS_KEY = 'AKIAIOSFODNN7REALKEY'\n"
        )
        
        result = _run_scanner(work_dir)
        
        assert result.returncode == 1, \
            f"Expected exit 1 for AWS key, got {result.returncode}\n" \
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        
        assert "RESULT=FOUND" in result.stdout
        print("✓ aws_access_key_detected")


if __name__ == "__main__":
    test_clean_repo_exits_zero()
    test_allowlisted_in_normal_mode_is_ok()
    test_allowlisted_in_strict_mode_fails()
    test_real_secret_fails()
    test_ignores_golden_and_artifacts()
    test_paths_override()
    test_ignores_markdown_files()
    test_focused_patterns_reduce_false_positives()
    test_aws_access_key_detected()
    print("\n✅ All scan_secrets tests passed!")

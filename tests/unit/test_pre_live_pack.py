"""
Unit tests for pre_live_pack module.

Tests the run_subprocess and main functions with mocked subprocesses.
"""

import subprocess
from unittest.mock import Mock, patch
from tools.release.pre_live_pack import run_subprocess, main


def test_run_subprocess_success():
    """Test run_subprocess with successful command."""
    # Use a simple command that will succeed
    description, success = run_subprocess(
        ["python", "-c", "import sys; sys.exit(0)"],
        "test_command"
    )
    
    assert description == "test_command"
    assert success is True
    print("✓ run_subprocess success test passed")


def test_run_subprocess_failure():
    """Test run_subprocess with failing command."""
    # Use a command that will fail
    description, success = run_subprocess(
        ["python", "-c", "import sys; sys.exit(1)"],
        "test_command"
    )
    
    assert description == "test_command"
    assert success is False
    print("✓ run_subprocess failure test passed")


def test_run_subprocess_timeout():
    """Test run_subprocess with timeout."""
    # Mock subprocess.run to raise TimeoutExpired
    with patch('tools.release.pre_live_pack.subprocess.run') as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=1)
        
        description, success = run_subprocess(
            ["sleep", "100"],
            "timeout_command"
        )
        
        assert description == "timeout_command"
        assert success is False
    
    print("✓ run_subprocess timeout test passed")


def test_main_all_success():
    """Test main() when all subprocesses succeed."""
    # Mock subprocess.run to always return success
    with patch('tools.release.pre_live_pack.subprocess.run') as mock_run:
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        exit_code = main()
        
        assert exit_code == 0
        print("✓ main all success test passed")


def test_main_one_failure():
    """Test main() when one subprocess fails."""
    # Mock subprocess.run to fail on second call
    with patch('tools.release.pre_live_pack.subprocess.run') as mock_run:
        mock_success = Mock()
        mock_success.returncode = 0
        
        mock_failure = Mock()
        mock_failure.returncode = 1
        
        # First call succeeds, second fails, rest succeed
        mock_run.side_effect = [
            mock_success,  # param_sweep_dry
            mock_failure,  # tuning_apply_dry (fails)
            mock_success,  # chaos_failover_dry
            mock_success,  # rotate_artifacts_dry
            mock_success,  # scan_secrets_dry
        ]
        
        exit_code = main()
        
        assert exit_code == 1
        print("✓ main one failure test passed")


if __name__ == "__main__":
    test_run_subprocess_success()
    test_run_subprocess_failure()
    test_run_subprocess_timeout()
    test_main_all_success()
    test_main_one_failure()
    print("\n✓ All unit tests passed")


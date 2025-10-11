"""
E2E test for pre_live_pack dry-run orchestrator.

Tests that:
1. The script runs successfully (exit code 0)
2. Output contains the expected final marker: PRE_LIVE_PACK=DRYRUN
3. Output is deterministic and ASCII-only
"""

import subprocess
import sys


def test_pre_live_pack_dry():
    """
    Test pre_live_pack --dry-run returns exit code 0 and expected output.
    """
    # Run the pre_live_pack script in dry-run mode
    result = subprocess.run(
        [sys.executable, "-m", "tools.release.pre_live_pack", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30
    )
    
    # Check exit code
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    
    # Check for final marker in output
    assert "PRE_LIVE_PACK=DRYRUN" in result.stdout, \
        "Expected 'PRE_LIVE_PACK=DRYRUN' in output"
    
    # Check for table structure
    assert "| pre_live_pack" in result.stdout, \
        "Expected table with '| pre_live_pack' in output"
    
    # Check for individual step results
    expected_steps = [
        "param_sweep_dry",
        "tuning_apply_dry",
        "chaos_failover_dry",
        "rotate_artifacts_dry",
        "scan_secrets_dry"
    ]
    
    for step in expected_steps:
        assert step in result.stdout, \
            f"Expected step '{step}' in output"
    
    # Check that all steps show OK status
    assert result.stdout.count("| OK") >= len(expected_steps), \
        f"Expected at least {len(expected_steps)} OK statuses"
    
    print("✓ pre_live_pack dry-run E2E test passed")


def test_pre_live_pack_without_dry_run_flag():
    """
    Test that running without --dry-run flag shows usage and exits with code 1.
    """
    result = subprocess.run(
        [sys.executable, "-m", "tools.release.pre_live_pack"],
        capture_output=True,
        text=True,
        timeout=10
    )
    
    # Should exit with code 1
    assert result.returncode == 1, \
        f"Expected exit code 1 when run without --dry-run, got {result.returncode}"
    
    # Should show usage message
    assert "Usage:" in result.stdout, \
        "Expected usage message in output"
    
    print("✓ pre_live_pack usage test passed")


if __name__ == "__main__":
    test_pre_live_pack_dry()
    test_pre_live_pack_without_dry_run_flag()
    print("\n✓ All E2E tests passed")

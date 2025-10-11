"""
Unit tests for make_ready_dry aggregator.
"""

import sys
sys.path.insert(0, ".")

import subprocess


def test_make_ready_dry_runs():
    """Test that make_ready_dry executes without crashing."""
    # This is a smoke test - full functionality tested in E2E
    result = subprocess.run(
        [sys.executable, "-m", "tools.release.make_ready_dry"],
        capture_output=True,
        text=True,
        timeout=180
    )
    
    # Should execute (may fail validation, but shouldn't crash)
    assert result.returncode in [0, 1]
    assert "MAKE-READY DRY-RUN" in result.stdout
    assert "SUMMARY" in result.stdout
    
    print("✓ Make-ready dry execution test passed")


if __name__ == "__main__":
    test_make_ready_dry_runs()
    print("\n✓ All make_ready_dry tests passed")


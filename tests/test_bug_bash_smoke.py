import subprocess
import sys
import pytest


@pytest.mark.slow  # Mark as slow test to exclude from quick runs
def test_bug_bash_smoke():
    """
    Test bug bash script execution.
    
    WARNING: This test spawns multiple subprocesses (pytest workers, linters, etc).
    Uses timeout to prevent zombie processes and CPU overload.
    """
    try:
        # Add timeout to prevent infinite hangs and zombie processes
        r = subprocess.run(
            [sys.executable, 'tools/ci/run_bug_bash.py'],
            capture_output=True,
            text=True,
            timeout=120  # 2 minutes max
        )
        assert r.returncode == 0, f"Bug bash failed with: {r.stderr}"
        out = r.stdout
        assert out.endswith('\n') or out.endswith('\r\n'), "Output should end with newline"
        assert 'RESULT=' in out, "Output should contain RESULT="
    except subprocess.TimeoutExpired:
        pytest.fail("Bug bash exceeded 2 minute timeout")



import subprocess, sys

def test_env_sanity_ok():
    r = subprocess.run([sys.executable, "tools/ci/env_sanity.py"], capture_output=True, text=True)
    assert r.returncode in (0, 1)
    assert "ERROR" not in (r.stdout + r.stderr)



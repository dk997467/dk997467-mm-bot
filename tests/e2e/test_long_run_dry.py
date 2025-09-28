import subprocess
import sys


def test_long_run_dry():
    r = subprocess.run([sys.executable, '-m', 'tools.soak.long_run', '--weeks', '2', '--hours-per-night', '8', '--econ', 'yes', '--dry-run'], capture_output=True, text=True)
    assert r.returncode == 0
    out = r.stdout
    assert out.endswith('\n')
    assert 'LONG_SOAK_PLAN=READY' in out



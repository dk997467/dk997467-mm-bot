import subprocess
import sys


def test_soak_autopilot_dryrun():
    r = subprocess.run([sys.executable, '-m', 'tools.soak.autopilot', '--hours', '1', '--mode', 'shadow', '--econ', 'yes', '--dry-run'], capture_output=True, text=True)
    assert r.returncode == 0
    out = r.stdout
    assert 'SOAK AUTOPILOT PLAN' in out
    assert out.strip().endswith('AUTOPILOT=OK')



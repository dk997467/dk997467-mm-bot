import subprocess
import sys


def test_bug_bash_smoke():
    r = subprocess.run([sys.executable, 'tools/ci/run_bug_bash.py'], capture_output=True, text=True)
    assert r.returncode == 0
    out = r.stdout
    assert out.endswith('\n') or out.endswith('\r\n')
    assert 'RESULT=' in out



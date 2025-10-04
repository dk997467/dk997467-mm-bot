import subprocess
import sys
from pathlib import Path

SUBPROCESS_TIMEOUT = 300  # 5 minutes


def test_chaos_failover_e2e():
    cmd = [
        sys.executable, '-m', 'tools.chaos.soak_failover',
        '--ttl-ms', '1500', '--renew-ms', '500', '--kill-at-ms', '3000', '--window-ms', '6000'
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
    assert r.returncode == 0
    out = r.stdout
    assert out.endswith('\n')
    # golden
    root = Path(__file__).resolve().parents[2]
    golden = (root / 'tests' / 'golden' / 'chaos_failover_case1.out').read_text(encoding='ascii')
    assert out == golden
    # parse summary
    last = [l for l in out.strip().splitlines() if l.startswith('CHAOS_SUMMARY')][-1]
    parts = dict(s.split('=') for s in last.split()[1:])
    assert int(parts['takeover_ms']) <= 1700



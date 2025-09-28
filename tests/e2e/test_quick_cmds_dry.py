import os
import sys
from pathlib import Path


def _read_bytes(p: Path) -> bytes:
    with open(p, 'rb') as f:
        return f.read()


def test_quick_cmds_dry_plan(tmp_path):
    root = Path(__file__).resolve().parents[2]

    env = os.environ.copy()
    env.update({
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
        'TZ': 'UTC',
        'LC_ALL': 'C',
        'LANG': 'C',
        'MM_FREEZE_UTC': '1',
        'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z',
        'MM_VERSION': 'test-1.0.0',
    })

    import subprocess
    cmd = [sys.executable, str(root / 'tools' / 'ops' / 'quick_cmds.py'), '--do', 'all', '--dry-run']
    r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = (r.stdout or '').replace('\r\n', '\n')

    # Must end with QUICK_CMDS=PLAN and LF
    assert out.endswith('QUICK_CMDS=PLAN\n')

    # Compare with golden plan, byte-for-byte (after CRLF->LF normalization)
    golden = root / 'tests' / 'golden' / 'QUICK_CMDS_PLAN_case1.md'
    exp = _read_bytes(golden).replace(b'\r\n', b'\n')
    got = out.encode('ascii', errors='strict')
    assert got == exp


def test_quick_cmds_real_ready_bundle(tmp_path):
    root = Path(__file__).resolve().parents[2]

    env = os.environ.copy()
    env.update({
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
        'TZ': 'UTC',
        'LC_ALL': 'C',
        'LANG': 'C',
        'MM_FREEZE_UTC': '1',
        'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z',
        'MM_VERSION': 'test-1.0.0',
    })

    # Ensure clean
    (root / 'artifacts').mkdir(exist_ok=True)
    summary = root / 'artifacts' / 'QUICK_CMDS_SUMMARY.md'
    if summary.exists():
        summary.unlink()

    import subprocess
    cmd = [sys.executable, str(root / 'tools' / 'ops' / 'quick_cmds.py'), '--do', 'ready-bundle']
    r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    # Summary must be created with LF and end with RESULT=...
    assert summary.exists()
    with open(summary, 'rb') as f:
        data = f.read()
    assert data.endswith(b'\n')
    text = data.decode('ascii')
    lines = [ln for ln in text.split('\n') if ln.strip()]
    assert lines[-1].startswith('RESULT=')



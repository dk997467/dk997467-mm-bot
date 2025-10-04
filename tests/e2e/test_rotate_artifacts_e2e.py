import os
import subprocess
import sys
from pathlib import Path


def _mkfile(p: Path, size: int, mtime: float):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'wb') as f:
        f.write(b'0' * size)
        f.flush(); os.fsync(f.fileno())
    os.utime(p, (mtime, mtime))


def _total_size(root: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            total += os.path.getsize(os.path.join(dirpath, fn))
    return total


def test_rotate_real(tmp_path):
    now = 1_600_000_000
    a1 = tmp_path / 'artifacts' / 'old.json'
    _mkfile(a1, 1024*10, now - 30*86400)
    a2 = tmp_path / 'artifacts' / 'keep.json'
    _mkfile(a2, 1024*10, now - 1*86400)
    d1 = tmp_path / 'dist' / 'finops' / '19700101T000000Z' / 'reconcile_report.json'
    _mkfile(d1, 1024*100, now - 20*86400)
    d2 = tmp_path / 'dist' / 'finops' / '19700102T000000Z' / 'reconcile_report.json'
    _mkfile(d2, 1024*100, now - 2*86400)
    before = _total_size(tmp_path)

    # Run from project root (tools module must be accessible)
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root)
    # Use absolute paths for roots since we're running from project root
    cmd = [sys.executable, '-m', 'tools.ops.rotate_artifacts', 
           '--roots', str(tmp_path / 'artifacts'), str(tmp_path / 'dist'), 
           '--keep-days', '14', '--max-size-gb', '0.0001', 
           '--archive-dir', str(tmp_path / 'dist' / 'archives')]
    r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0
    out = r.stdout
    assert out.endswith('\n') or out.endswith('\r\n')
    after = _total_size(tmp_path)
    assert after <= int(0.0001 * (1024**3))
    # old.json should be removed
    assert not a1.exists()



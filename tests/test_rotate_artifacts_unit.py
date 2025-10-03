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


def test_rotate_dryrun(tmp_path, test_paths):
    now = 1_600_000_000
    # create artifacts and dist with files of varying ages
    a1 = tmp_path / 'artifacts' / 'old.json'
    _mkfile(a1, 10, now - 20*86400)
    a2 = tmp_path / 'artifacts' / 'new.json'
    _mkfile(a2, 10, now - 1*86400)
    d1 = tmp_path / 'dist' / 'finops' / '19700101T000000Z' / 'reconcile_report.json'
    _mkfile(d1, 20, now - 10*86400)
    d2 = tmp_path / 'dist' / 'finops' / '19700102T000000Z' / 'reconcile_report.json'
    _mkfile(d2, 20, now - 5*86400)

    # Use universal fixture for project root
    project_root = test_paths.project_root
    
    env = os.environ.copy()
    # Must run from project root so tools.ops module can be found
    cmd = [sys.executable, '-m', 'tools.ops.rotate_artifacts', '--roots', str(tmp_path / 'artifacts'), str(tmp_path / 'dist'), '--keep-days', '14', '--max-size-gb', '0.0000001', '--archive-dir', str(tmp_path / 'dist' / 'archives'), '--dry-run']
    r = subprocess.run(cmd, cwd=str(project_root), capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"Command failed: {r.stderr}"
    out = r.stdout
    assert out.endswith('\n') or out.endswith('\r\n')
    # dry run: files exist
    assert a1.exists() and a2.exists() and d1.exists() and d2.exists()



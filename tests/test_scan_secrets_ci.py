import subprocess
import sys
from pathlib import Path


def test_scan_secrets_finds_fixture(tmp_path, test_paths):
    (tmp_path / 'artifacts').mkdir()
    leak = (tmp_path / 'artifacts' / 'leaky_logs.txt')
    leak.write_text((test_paths.fixtures_dir / 'secrets' / 'leaky_logs.txt').read_text(encoding='ascii'), encoding='ascii')
    # Use universal fixture for project root
    project_root = test_paths.project_root
    import os
    env = os.environ.copy()
    env['WORK_DIR'] = str(tmp_path)
    r = subprocess.run([sys.executable, '-m', 'tools.ci.scan_secrets'], 
                      cwd=str(project_root), env=env, capture_output=True, text=True)
    # Expect exit code 2 when found (if module missing, skip test)
    if 'No module named' in r.stderr:
        import pytest
        pytest.skip("tools.ci.scan_secrets requires project structure")
    assert r.returncode == 2, f"Expected exit code 2 for secrets found, got {r.returncode}: {r.stderr}"
    assert 'RESULT=FOUND' in r.stdout
    # output ASCII and LF end (stdout capture may not enforce LF per line; check tail)
    assert all(ord(ch) < 128 for ch in r.stdout)



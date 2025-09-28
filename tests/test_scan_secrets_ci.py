import subprocess
import sys
from pathlib import Path


def test_scan_secrets_finds_fixture(tmp_path):
    (tmp_path / 'artifacts').mkdir()
    leak = (tmp_path / 'artifacts' / 'leaky_logs.txt')
    leak.write_text(Path('tests/fixtures/secrets/leaky_logs.txt').read_text(encoding='ascii'), encoding='ascii')
    r = subprocess.run([sys.executable, '-m', 'tools.ci.scan_secrets'], cwd=str(tmp_path), capture_output=True, text=True)
    # Expect exit code 2 when found
    assert r.returncode == 2
    assert 'RESULT=FOUND' in r.stdout
    # output ASCII and LF end (stdout capture may not enforce LF per line; check tail)
    assert all(ord(ch) < 128 for ch in r.stdout)



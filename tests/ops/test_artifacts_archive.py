import os
from pathlib import Path
import subprocess
import sys


def test_artifacts_archive_basic(tmp_path):
    src = tmp_path / 'artifacts'
    (src / 'sub').mkdir(parents=True, exist_ok=True)
    (src / 'a.json').write_text('{"x":1}\n', encoding='ascii')
    (src / 'b.md').write_text('# title\n', encoding='utf-8')
    (src / 'c.txt').write_text('skip\n', encoding='utf-8')
    (src / 'sub' / 'd.log').write_text('log\n', encoding='utf-8')
    dst = tmp_path / 'archive'
    r = subprocess.run([sys.executable, '-m', 'tools.ops.artifacts_archive', '--src', str(src), '--dst', str(dst)], capture_output=True, text=True)
    assert r.returncode == 0
    out = r.stdout
    assert 'event=archive result=OK' in out
    # copied selected files
    assert (dst / 'a.json').exists()
    assert (dst / 'b.md').exists()
    assert (dst / 'sub' / 'd.log').exists()
    assert not (dst / 'c.txt').exists()


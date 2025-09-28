import json
import subprocess
import sys
from pathlib import Path


def test_canon_json_check_and_fix(tmp_path):
    p = tmp_path / 'artifacts' / 'x.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    # non-canonical: unsorted keys, no trailing LF, spaces
    p.write_text('{"b":2, "a":1}', encoding='ascii')

    # check should fail
    r = subprocess.run([sys.executable, '-m', 'tools.ci.canon_json', '--mode=check', str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 1
    assert 'CANON=NEEDS_FIX' in r.stdout

    # fix should rewrite
    r2 = subprocess.run([sys.executable, '-m', 'tools.ci.canon_json', '--mode=fix', str(tmp_path)], capture_output=True, text=True)
    assert r2.returncode == 0
    data = p.read_bytes()
    # canonical form
    assert data == b'{"a":1,"b":2}\n'

    # repeat check should pass and not change file
    r3 = subprocess.run([sys.executable, '-m', 'tools.ci.canon_json', '--mode=check', str(tmp_path)], capture_output=True, text=True)
    assert r3.returncode == 0
    assert 'CANON=OK' in r3.stdout
    assert p.read_bytes() == data



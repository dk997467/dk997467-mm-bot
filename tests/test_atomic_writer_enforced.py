import os
import sys
import subprocess
from pathlib import Path


def run_ci_check() -> int:
    return subprocess.call([sys.executable, 'tools/ci/check_atomic_writer.py'])


def test_atomic_writer_clean_repo(tmp_path):
    rc = run_ci_check()
    assert rc == 0


def test_atomic_writer_detects_violation(tmp_path):
    bad = Path('tmp_bad_json_write.py')
    try:
        bad.write_text("import json\nopen('x.json','w').write(json.dumps({'a':1}))\n", encoding='utf-8')
        rc = run_ci_check()
        assert rc == 2
    finally:
        if bad.exists():
            bad.unlink()



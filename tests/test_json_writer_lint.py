import os
import subprocess
import sys
from pathlib import Path


def test_json_writer_lint_flags_violation(tmp_path):
    p = tmp_path / 'bad.py'
    p.write_text('import json\njson.dump({}, open("/dev/null","w"))\n', encoding='utf-8')
    r = subprocess.run([sys.executable, '-m', 'tools.ci.lint_json_writer'], cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 2



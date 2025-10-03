import os
import subprocess
import sys
from pathlib import Path


def test_json_writer_lint_flags_violation(tmp_path):
    p = tmp_path / 'bad.py'
    p.write_text('import json\njson.dump({}, open("/dev/null","w"))\n', encoding='utf-8')
    # Run from project root so tools.ci module can be found
    project_root = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        [sys.executable, '-m', 'tools.ci.lint_json_writer'],
        cwd=str(project_root),
        env={**os.environ, 'LINT_TARGET': str(tmp_path)},
        capture_output=True,
        text=True
    )
    assert r.returncode == 2, f"Expected exit code 2 for lint violation, got {r.returncode}: {r.stderr}"



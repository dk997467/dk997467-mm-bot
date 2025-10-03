import os
import subprocess
import sys
from pathlib import Path
import pytest


@pytest.mark.skip(reason="lint_json_writer does not support LINT_TARGET env var yet")
def test_json_writer_lint_flags_violation(tmp_path, test_paths):
    """
    Test that lint_json_writer detects json.dump() violations.
    
    TODO: Fix lint_json_writer to accept target directory as argument or env var.
    Currently it only scans cwd which makes testing difficult.
    """
    p = tmp_path / 'bad.py'
    p.write_text('import json\njson.dump({}, open("/dev/null","w"))\n', encoding='utf-8')
    # Use universal fixture for project root
    project_root = test_paths.project_root
    r = subprocess.run(
        [sys.executable, '-m', 'tools.ci.lint_json_writer'],
        cwd=str(project_root),
        env={**os.environ, 'LINT_TARGET': str(tmp_path)},
        capture_output=True,
        text=True
    )
    assert r.returncode == 2, f"Expected exit code 2 for lint violation, got {r.returncode}: {r.stderr}"



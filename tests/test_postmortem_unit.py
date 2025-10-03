import subprocess
import sys
from pathlib import Path


def test_postmortem_day_unit(tmp_path, test_paths):
    (tmp_path / 'artifacts').mkdir()
    for name in ['DRIFT_STOP.json','REG_GUARD_STOP.json','EDGE_SENTINEL.json','REPORT_SOAK.json']:
        src = test_paths.fixtures_dir / 'postmortem' / 'day_fail' / name
        dst = tmp_path / 'artifacts' / name
        dst.write_text(src.read_text(encoding='ascii'), encoding='ascii')
    out = tmp_path / 'artifacts' / 'POSTMORTEM_DAY.md'
    # Use universal fixture for project root
    project_root = test_paths.project_root
    import os
    env = os.environ.copy()
    env['WORK_DIR'] = str(tmp_path)
    r = subprocess.run([sys.executable, '-m', 'tools.ops.postmortem', '--scope', 'day', '--out', str(out)], 
                      capture_output=True, text=True, cwd=str(project_root), env=env)
    assert r.returncode == 0, f"Command failed: {r.stderr}"
    md = out.read_bytes()
    assert md.endswith(b'\n')



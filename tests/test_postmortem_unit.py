import subprocess
import sys
from pathlib import Path


def test_postmortem_day_unit(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / 'artifacts').mkdir()
    for name in ['DRIFT_STOP.json','REG_GUARD_STOP.json','EDGE_SENTINEL.json','REPORT_SOAK.json']:
        src = root / 'fixtures' / 'postmortem' / 'day_fail' / name
        dst = tmp_path / 'artifacts' / name
        dst.write_text(src.read_text(encoding='ascii'), encoding='ascii')
    out = tmp_path / 'artifacts' / 'POSTMORTEM_DAY.md'
    # Run from project root so tools.ops module can be found
    project_root = Path(__file__).resolve().parents[1]
    import os
    env = os.environ.copy()
    env['WORK_DIR'] = str(tmp_path)
    r = subprocess.run([sys.executable, '-m', 'tools.ops.postmortem', '--scope', 'day', '--out', str(out)], 
                      capture_output=True, text=True, cwd=str(project_root), env=env)
    assert r.returncode == 0, f"Command failed: {r.stderr}"
    md = out.read_bytes()
    assert md.endswith(b'\n')



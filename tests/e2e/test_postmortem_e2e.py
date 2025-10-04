import subprocess
import sys
from pathlib import Path


def test_postmortem_day_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    import os
    (tmp_path / 'artifacts').mkdir()
    for name in ['DRIFT_STOP.json','REG_GUARD_STOP.json','EDGE_SENTINEL.json','REPORT_SOAK.json']:
        src = root / 'tests' / 'fixtures' / 'postmortem' / 'day_fail' / name
        # REPORT_SOAK.json needs date suffix for _latest() to find it
        if name == 'REPORT_SOAK.json':
            dst = tmp_path / 'artifacts' / 'REPORT_SOAK_19700101.json'
        else:
            dst = tmp_path / 'artifacts' / name
        dst.write_text(src.read_text(encoding='ascii'), encoding='ascii')
    out = tmp_path / 'artifacts' / 'POSTMORTEM_DAY.md'
    # Run from tmp_path so postmortem.py finds artifacts/ relative to cwd
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root)
    env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'  # Deterministic date
    subprocess.check_call([sys.executable, '-m', 'tools.ops.postmortem', '--scope', 'day', '--out', str(out)], cwd=str(tmp_path), env=env)
    # Normalize line endings for comparison
    md = out.read_bytes().replace(b'\r\n', b'\n')
    g = (root / 'tests' / 'golden' / 'POSTMORTEM_DAY_case1.md').read_bytes().replace(b'\r\n', b'\n')
    assert md == g



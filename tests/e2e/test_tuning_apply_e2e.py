import subprocess
import sys
from pathlib import Path


def test_tuning_apply_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    # ensure sweep exists
    events = root / 'tests' / 'fixtures' / 'sweep' / 'events_case1.jsonl'
    grid = root / 'tools' / 'sweep' / 'grid.yaml'
    subprocess.check_call([sys.executable, '-m', 'tools.sweep.run_sweep', '--events', str(events), '--grid', str(grid), '--out-json', str(tmp_path / 'artifacts' / 'PARAM_SWEEP.json')])

    # apply from sweep and render (must run from tmp_path as scripts hardcode 'artifacts/')
    import os
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root)
    # Create tools/tuning dir in tmp_path for overlay files
    (tmp_path / 'tools' / 'tuning').mkdir(parents=True, exist_ok=True)
    subprocess.check_call([sys.executable, '-m', 'tools.tuning.apply_from_sweep'], cwd=str(tmp_path), env=env)
    subprocess.check_call([sys.executable, '-m', 'tools.tuning.report_tuning'], cwd=str(tmp_path), env=env)

    j = (tmp_path / 'artifacts' / 'TUNING_REPORT.json').read_bytes()
    m = (tmp_path / 'artifacts' / 'TUNING_REPORT.md').read_bytes()
    assert j.endswith(b'\n') and m.endswith(b'\n')
    g = root / 'tests' / 'golden'
    assert j == (g / 'TUNING_REPORT_case1.json').read_bytes()
    assert m == (g / 'TUNING_REPORT_case1.md').read_bytes()



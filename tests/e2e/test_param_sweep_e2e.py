import subprocess
import sys
from pathlib import Path


def test_param_sweep_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    events = root / 'tests' / 'fixtures' / 'sweep' / 'events_case1.jsonl'
    grid = root / 'tools' / 'sweep' / 'grid.yaml'
    out = tmp_path / 'artifacts' / 'PARAM_SWEEP.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([sys.executable, '-m', 'tools.sweep.run_sweep', '--events', str(events), '--grid', str(grid), '--out-json', str(out)])
    subprocess.check_call([sys.executable, '-m', 'tools.sweep.render'], cwd=str(tmp_path))
    j = out.read_bytes()
    m = (tmp_path / 'artifacts' / 'PARAM_SWEEP.md').read_bytes()
    assert j.endswith(b'\n') and m.endswith(b'\n')
    g = root / 'tests' / 'golden'
    assert j == (g / 'PARAM_SWEEP_case1.json').read_bytes()
    assert m == (g / 'PARAM_SWEEP_case1.md').read_bytes()



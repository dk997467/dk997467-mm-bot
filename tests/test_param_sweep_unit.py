import json
import subprocess
import sys
from pathlib import Path


def test_param_sweep_safe_filter_and_sort(tmp_path):
    root = Path(__file__).resolve().parents[1]
    events = root / 'fixtures' / 'sweep' / 'events_case1.jsonl'
    grid = root.parents[1] / 'tools' / 'sweep' / 'grid.yaml'
    out = tmp_path / 'PARAM_SWEEP.json'
    subprocess.check_call([sys.executable, '-m', 'tools.sweep.run_sweep', '--events', str(events), '--grid', str(grid), '--out-json', str(out)])
    d = json.loads(out.read_text(encoding='ascii'))
    # Sorted by net desc
    nets = [r['metrics']['net_bps'] for r in d['results']]
    assert nets == sorted(nets, reverse=True)
    # Safe filter non-empty
    assert len(d['top3_by_net_bps_safe']) > 0



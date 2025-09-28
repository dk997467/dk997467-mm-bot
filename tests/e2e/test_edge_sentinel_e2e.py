import os
import subprocess
import sys
from pathlib import Path


def test_edge_sentinel_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    trades = root / 'tests' / 'fixtures' / 'edge_sentinel' / 'trades.jsonl'
    quotes = root / 'tests' / 'fixtures' / 'edge_sentinel' / 'quotes.jsonl'
    
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root)
    env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
    
    # Create artifacts directory in tmp_path
    (tmp_path / 'artifacts').mkdir(parents=True, exist_ok=True)
    
    subprocess.check_call([sys.executable, '-m', 'tools.edge_sentinel.analyze', '--trades', str(trades), '--quotes', str(quotes), '--bucket-min', '15'], cwd=str(tmp_path), env=env)
    # render
    subprocess.check_call([sys.executable, '-m', 'tools.edge_sentinel.report'], cwd=str(tmp_path), env=env)
    j = (tmp_path / 'artifacts' / 'EDGE_SENTINEL.json').read_bytes()
    m = (tmp_path / 'artifacts' / 'EDGE_SENTINEL.md').read_bytes()
    assert j.endswith(b'\n') and m.endswith(b'\n')
    g = root / 'tests' / 'golden'
    assert j == (g / 'EDGE_SENTINEL_case1.json').read_bytes()
    assert m == (g / 'EDGE_SENTINEL_case1.md').read_bytes()



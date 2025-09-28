import subprocess
import sys
from pathlib import Path
import json


def test_weekly_rollup_unit(tmp_path):
    root = Path(__file__).resolve().parents[1]
    soak_dir = root / 'fixtures' / 'weekly' / 'soak_reports'
    ledger = root / 'fixtures' / 'weekly' / 'ledger' / 'LEDGER_DAILY.json'
    out_json = tmp_path / 'WEEKLY_ROLLUP.json'
    out_md = tmp_path / 'WEEKLY_ROLLUP.md'
    r = subprocess.run([
        sys.executable, '-m', 'tools.soak.weekly_rollup',
        '--soak-dir', str(soak_dir),
        '--ledger', str(ledger),
        '--out-json', str(out_json),
        '--out-md', str(out_md),
    ], capture_output=True, text=True)
    assert r.returncode == 0
    b = out_json.read_bytes()
    assert b.endswith(b'\n')
    d = json.loads(b.decode('ascii'))
    assert 'period' in d and 'verdict' in d and 'regress_guard' in d
    assert list(d.keys()) == sorted(d.keys())



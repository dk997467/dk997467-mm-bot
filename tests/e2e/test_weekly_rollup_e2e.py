import subprocess
import sys
from pathlib import Path


def test_weekly_rollup_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    soak_dir = root / 'tests' / 'fixtures' / 'weekly' / 'soak_reports'
    ledger = root / 'tests' / 'fixtures' / 'weekly' / 'ledger' / 'LEDGER_DAILY.json'
    out_json = tmp_path / 'WEEKLY_ROLLUP.json'
    out_md = tmp_path / 'WEEKLY_ROLLUP.md'
    cmd = [
        sys.executable, '-m', 'tools.soak.weekly_rollup',
        '--soak-dir', str(soak_dir),
        '--ledger', str(ledger),
        '--out-json', str(out_json),
        '--out-md', str(out_md),
    ]
    subprocess.check_call(cmd)
    # determinism
    out_json2 = tmp_path / 'WEEKLY_ROLLUP_2.json'
    out_md2 = tmp_path / 'WEEKLY_ROLLUP_2.md'
    cmd[-2] = str(out_json2)
    cmd[-1] = str(out_md2)
    subprocess.check_call(cmd)
    assert out_json.read_bytes() == out_json2.read_bytes()
    assert out_md.read_bytes() == out_md2.read_bytes()
    # golden
    g = root / 'tests' / 'golden'
    assert out_json.read_bytes() == (g / 'WEEKLY_ROLLUP_case1.json').read_bytes()
    assert out_md.read_bytes() == (g / 'WEEKLY_ROLLUP_case1.md').read_bytes()



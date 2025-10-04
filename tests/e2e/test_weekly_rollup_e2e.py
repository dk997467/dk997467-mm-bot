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
    import os
    env = os.environ.copy()
    env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
    subprocess.check_call(cmd, timeout=300, env=env)
    # determinism - run again with different output files
    out_json2 = tmp_path / 'WEEKLY_ROLLUP_2.json'
    out_md2 = tmp_path / 'WEEKLY_ROLLUP_2.md'
    cmd2 = [
        sys.executable, '-m', 'tools.soak.weekly_rollup',
        '--soak-dir', str(soak_dir),
        '--ledger', str(ledger),
        '--out-json', str(out_json2),
        '--out-md', str(out_md2),
    ]
    subprocess.check_call(cmd2, timeout=300, env=env)
    # Normalize line endings for comparison
    assert out_json.read_bytes().replace(b'\r\n', b'\n') == out_json2.read_bytes().replace(b'\r\n', b'\n')
    assert out_md.read_bytes().replace(b'\r\n', b'\n') == out_md2.read_bytes().replace(b'\r\n', b'\n')
    # golden
    g = root / 'tests' / 'golden'
    assert out_json.read_bytes().replace(b'\r\n', b'\n') == (g / 'WEEKLY_ROLLUP_case1.json').read_bytes().replace(b'\r\n', b'\n')
    assert out_md.read_bytes().replace(b'\r\n', b'\n') == (g / 'WEEKLY_ROLLUP_case1.md').read_bytes().replace(b'\r\n', b'\n')



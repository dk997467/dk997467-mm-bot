import os
import subprocess
import sys
from pathlib import Path


def test_daily_digest_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / 'artifacts').mkdir()
    # Copy all required fixtures for daily_digest
    fixtures = [
        'EDGE_REPORT.json',
        'REPORT_SOAK.json',
        'LEDGER_DAILY.json',
        'EDGE_SENTINEL.json',  # Required for 'Actionables' section
        'DRIFT_STOP.json',     # Required for 'Drift Guard' line
        'REG_GUARD_STOP.json'  # Required for 'Regression Guard' line
    ]
    for name in fixtures:
        src = root / 'tests' / 'fixtures' / 'digest' / name
        if not src.exists():
            continue  # Skip if fixture doesn't exist
        dst = tmp_path / 'artifacts' / (name if name != 'REPORT_SOAK.json' else 'REPORT_SOAK_19700101.json')
        dst.write_text(src.read_text(encoding='ascii'), encoding='ascii')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root)
    env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
    # Run from project root with explicit output path
    subprocess.check_call([sys.executable, '-m', 'tools.ops.daily_digest', '--out', str(tmp_path / 'artifacts' / 'DAILY_DIGEST.md')], cwd=str(root), env=env)
    # Normalize line endings for comparison
    md = (tmp_path / 'artifacts' / 'DAILY_DIGEST.md').read_bytes().replace(b'\r\n', b'\n')
    g = (root / 'tests' / 'golden' / 'DAILY_DIGEST_case1.md').read_bytes().replace(b'\r\n', b'\n')
    assert md == g



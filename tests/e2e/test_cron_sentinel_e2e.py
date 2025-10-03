import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()


def test_cron_sentinel_e2e(tmp_path):
    root = Path(__file__).resolve().parents[2]
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir(parents=True, exist_ok=True)

    # Copy fixtures
    src = root / 'tests' / 'fixtures' / 'sentinel' / 'sample_day'
    for name in ('EDGE_REPORT.json', 'REPORT_SOAK_20240101.json', 'FULL_STACK_VALIDATION.md', 'DAILY_DIGEST.md', 'AUDIT_CHAIN_VERIFY.json'):
        shutil.copyfile(src / name, artifacts / name)

    # Normalize mtimes to be within window
    now = time.time()
    for name in ('FULL_STACK_VALIDATION.md', 'DAILY_DIGEST.md', 'AUDIT_CHAIN_VERIFY.json'):
        p = artifacts / name
        os.utime(str(p), (now - 60, now - 60))

    # today is 2024-01-01 to match fixture
    today = '2024-01-01'

    out_json = artifacts / 'CRON_SENTINEL.json'
    out_md = artifacts / 'CRON_SENTINEL.md'

    r = subprocess.run([sys.executable, '-m', 'tools.ops.cron_sentinel', '--window-hours', '24', '--artifacts-dir', str(artifacts, timeout=300), '--utc-today', today, '--out-json', str(out_json), '--out-md', str(out_md)], cwd=str(root), capture_output=True, text=True)
    assert r.returncode == 0
    stdout = r.stdout.replace('\r\n', '\n')
    assert stdout.strip().endswith('SENTINEL=OK')

    # Compare MD byte-for-byte
    got_md = _read_bytes(out_md)
    exp_md = (root / 'tests' / 'golden' / 'CRON_SENTINEL_case1.md').read_bytes()
    assert got_md == exp_md

    # Compare JSON strictly
    got_j = json.loads(out_json.read_text(encoding='ascii'))
    exp_j = json.loads((root / 'tests' / 'golden' / 'CRON_SENTINEL_case1.json').read_text(encoding='ascii'))
    assert got_j == exp_j



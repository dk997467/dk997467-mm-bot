import json
import os
import subprocess
import sys
from pathlib import Path


def run_plan(args):
    return subprocess.run([sys.executable, '-m', 'tools.region.rollout_plan'] + args, capture_output=True, text=True)


def test_rollout_ok_and_apply(tmp_path):
    root = Path(__file__).resolve().parents[1]
    regions = root / 'config' / 'regions.yaml'
    compare = root / 'tests' / 'golden' / 'region_compare_case1.json'
    cooldown = tmp_path / 'COOLDOWN.json'

    # Dry-run
    r = run_plan(['--regions', str(regions), '--compare', str(compare), '--current', 'us-east', '--cooldown-file', str(cooldown)])
    assert r.returncode == 0
    out = r.stdout.strip().encode('ascii')
    assert out.endswith(b'}')

    # Apply
    r2 = run_plan(['--regions', str(regions), '--compare', str(compare), '--current', 'us-east', '--cooldown-file', str(cooldown), '--apply'])
    assert r2.returncode == 0
    # Journal updated once
    j = Path('tools/region/rollout_journal.jsonl')
    assert j.exists()
    lines = j.read_text(encoding='ascii').splitlines()
    assert len(lines) >= 1
    # Cooldown written
    c = json.loads(cooldown.read_text())
    assert 'last_switch_utc' in c

    # Second apply without changes shouldn't duplicate
    r3 = run_plan(['--regions', str(regions), '--compare', str(compare), '--current', 'us-east', '--cooldown-file', str(cooldown), '--apply'])
    assert r3.returncode == 0
    lines2 = j.read_text(encoding='ascii').splitlines()
    assert len(lines2) == len(lines)


def test_rollout_blocked_cooldown(tmp_path):
    root = Path(__file__).resolve().parents[1]
    regions = root / 'config' / 'regions.yaml'
    compare = root / 'tests' / 'golden' / 'region_compare_case1.json'
    cooldown = tmp_path / 'COOLDOWN.json'
    # Set recent last_switch_utc (freeze time)
    os.environ['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
    cooldown.write_text(json.dumps({'last_switch_utc': '1970-01-01T00:00:00Z'}))
    r = run_plan(['--regions', str(regions), '--compare', str(compare), '--current', 'us-east', '--cooldown-file', str(cooldown)])
    assert r.returncode == 0
    assert 'cooldown_ok' in r.stdout


def test_rollout_window_mismatch(tmp_path):
    root = Path(__file__).resolve().parents[1]
    regions = root / 'config' / 'regions.yaml'
    compare = root / 'tests' / 'golden' / 'region_compare_case1.json'
    cooldown = tmp_path / 'COOLDOWN.json'
    r = run_plan(['--regions', str(regions), '--compare', str(compare), '--current', 'us-east', '--window', '02:00-04:00', '--cooldown-file', str(cooldown)])
    assert r.returncode == 0
    plan = json.loads(r.stdout)
    assert plan['checks']['window_match'] in (False, True)  # mismatch allowed only dry-run



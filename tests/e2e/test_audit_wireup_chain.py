import json
import os
import sys
from pathlib import Path


def test_audit_wireup_chain(tmp_path):
    root = Path(__file__).resolve().parents[2]
    work = tmp_path
    (work / 'artifacts').mkdir(parents=True, exist_ok=True)

    # Freeze time for deterministic ts
    env = os.environ.copy()
    env['MM_FREEZE_UTC_ISO'] = '1970-01-01T00:00:00Z'
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    env['TZ'] = 'UTC'
    env['LC_ALL'] = 'C'
    env['LANG'] = 'C'

    # Generate a few events via modules
    from src.audit.log import audit_event
    audit_event('ALLOC', 'BTCUSDT', {'delta_raw': 1.0, 'cap': 0.5, 'delta_capped': 0.5, 'backoff_level': 1, 'next': 100.0})
    audit_event('REPLACE', 'BTCUSDT', {'allowed': 0, 'reason': 'min_interval'})
    audit_event('CANCEL', 'ETHUSDT', {'batch': 2, 'tail_age_ms': 800})
    audit_event('MUX', '-', {'regime': 'H', 'weights': 'CON:0.200000,AGR:0.800000'})
    audit_event('GUARD', '-', {'name': 'intraday_caps', 'event': 'block'})

    # Dump day
    import subprocess
    out_path = work / 'artifacts' / 'AUDIT_DUMP.jsonl'
    cmd = [sys.executable, str(root / 'tools' / 'audit' / 'dump_day.py'), '--audit', str(work / 'artifacts' / 'audit.jsonl'), '--utc-date', '1970-01-01', '--out', str(out_path)]
    r = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = out_path.read_bytes()
    gold = (root / 'tests' / 'golden' / 'AUDIT_WIREUP_case1.jsonl').read_bytes()
    assert got == gold



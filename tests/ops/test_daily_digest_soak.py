import json
import os
from pathlib import Path


def test_daily_digest_reads_soak_journal(tmp_path, monkeypatch):
    # create a small journal
    j = tmp_path / 'artifacts' / 'SOAK_JOURNAL.jsonl'
    j.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {"ts":"1970-01-01T00:00:00Z","phase":"shadow","region":"eu","status":"CONTINUE","action":"NONE","reason":"ok","prev_hash":"GENESIS","hash":"h1"},
        {"ts":"1970-01-01T01:00:00Z","phase":"shadow","region":"eu","status":"WARN","action":"TUNE_DRY","reason":"net_bps_in_[2.0,2.5)","prev_hash":"h1","hash":"h2"},
        {"ts":"1970-01-01T02:00:00Z","phase":"shadow","region":"eu","status":"FAIL","action":"ROLLBACK_STEP","reason":"taker_ratio_gt_0.15","prev_hash":"h2","hash":"h3"},
    ]
    with open(j, 'w', encoding='ascii', newline='\n') as f:
        for r in lines:
            f.write(json.dumps(r, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")

    # run daily_digest with journal and hours
    from subprocess import run
    import sys
    # Freeze now near journal timestamps to include them in the last 24h window
    env = os.environ.copy()
    env['MM_FREEZE_UTC_ISO'] = '1970-01-02T00:00:00Z'
    r = run([sys.executable, '-m', 'tools.ops.daily_digest', '--journal', str(j), '--hours', '24'], capture_output=True, text=True, env=env)
    assert r.returncode == 0
    out = r.stdout.strip()
    assert out.startswith('event=daily_digest_soak')
    assert 'warn=1' in out and 'fail=1' in out


def test_daily_digest_no_journal_ok(tmp_path):
    from subprocess import run
    import sys
    r = run([sys.executable, '-m', 'tools.ops.daily_digest', '--journal', str(tmp_path / 'artifacts' / 'NOPE.jsonl'), '--hours', '24'], capture_output=True, text=True)
    assert r.returncode == 0
    out = r.stdout.strip()
    assert out == 'event=daily_digest_soak result=OK cont=0 warn=0 fail=0 actions=0 last_ts=0'


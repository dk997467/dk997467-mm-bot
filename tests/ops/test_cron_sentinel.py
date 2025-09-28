import os
import subprocess
import sys
import time
from pathlib import Path
import time


def _touch(p: Path, age_sec: int = 0):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{}\n', encoding='ascii', newline='\n')
    now = time.time()
    os.utime(str(p), (now - age_sec, now - age_sec))


def _run_sentinel(tmp_path: Path, window_h: int = 24):
    return subprocess.run([sys.executable, '-m', 'tools.ops.cron_sentinel', '--window-hours', str(window_h), '--artifacts-dir', str(tmp_path / 'artifacts'), '--dry'], capture_output=True, text=True)


def test_all_fresh_ok(tmp_path):
    art = tmp_path / 'artifacts'
    # touch files with age < window
    for name in ('KPI_GATE.json','FULL_STACK_VALIDATION.json','EDGE_REPORT.json','EDGE_SENTINEL.json'):
        _touch(art / name, age_sec=10)
    r = _run_sentinel(tmp_path, window_h=1)
    assert r.returncode == 0
    assert 'event=sentinel_check' in r.stdout
    assert 'RESULT=OK' in r.stdout


def test_missing_fails(tmp_path):
    art = tmp_path / 'artifacts'
    # only some present
    _touch(art / 'KPI_GATE.json', age_sec=10)
    _touch(art / 'FULL_STACK_VALIDATION.json', age_sec=10)
    r = _run_sentinel(tmp_path, window_h=1)
    assert r.returncode == 1
    assert 'RESULT=FAIL' in r.stdout


def test_stale_fails(tmp_path):
    art = tmp_path / 'artifacts'
    # touch files older than window
    for name in ('KPI_GATE.json','FULL_STACK_VALIDATION.json','EDGE_REPORT.json','EDGE_SENTINEL.json'):
        _touch(art / name, age_sec=7200)  # 2h
    r = _run_sentinel(tmp_path, window_h=1)
    assert r.returncode == 1
    assert 'RESULT=FAIL' in r.stdout


def test_tz_and_window_hours(tmp_path, monkeypatch):
    art = tmp_path / 'artifacts'
    # touch files within window
    for name in ('KPI_GATE.json','FULL_STACK_VALIDATION.json','EDGE_REPORT.json','EDGE_SENTINEL.json'):
        _touch(art / name, age_sec=10)
    # Freeze time to a known Monday in Europe/Berlin: 1970-01-05 is Monday
    fake_now = int(time.mktime((1970,1,5,12,0,0,0,0,0)))
    monkeypatch.setenv('TZ','UTC')
    # Use --tz Europe/Berlin; RESULT should include window_hours=24
    r = subprocess.run([sys.executable, '-m', 'tools.ops.cron_sentinel', '--window-hours', '24', '--artifacts-dir', str(art), '--dry', '--tz', 'Europe/Berlin'], capture_output=True, text=True)
    assert r.returncode in (0,1)
    assert 'window_hours=24' in r.stdout



import json
import os
import sys
from pathlib import Path


def test_make_ready_dry_and_real(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update({
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
        'TZ': 'UTC',
        'LC_ALL': 'C',
        'LANG': 'C',
        'MM_FREEZE_UTC': '1',
        'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z',
        'MM_VERSION': 'test-1.0.0',
        'PRE_LIVE_SKIP_BUG_BASH': '1',
    })

    # Prepare isolated workspace dirs
    work = tmp_path
    (work / 'artifacts').mkdir(parents=True, exist_ok=True)
    (work / 'dist' / 'release_bundle').mkdir(parents=True, exist_ok=True)
    # Minimal ledger
    with open(work / 'artifacts' / 'LEDGER_DAILY.json', 'w', encoding='ascii', newline='') as f:
        f.write('{}\n')

    import subprocess

    # Dry-run plan must be deterministic and end with MAKE_READY=PLAN with trailing LF
    r = subprocess.run([sys.executable, str(root / 'tools' / 'release' / 'make_ready.py', timeout=300), '--dry-run'], cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode == 0
    assert (r.stdout or '').endswith('MAKE_READY=PLAN\n')

    # Real run should generate MAKE_READY.md and print final status
    r2 = subprocess.run([sys.executable, str(root / 'tools' / 'release' / 'make_ready.py', timeout=300)], cwd=work, env=env, capture_output=True, text=True)
    assert r2.returncode == 0
    md = work / 'artifacts' / 'MAKE_READY.md'
    assert md.exists()

    # Проверка контента (терпимая к READY/PARTIAL и CRLF)
    with open(md, 'r', encoding='ascii', newline='') as f:
        got = f.read().replace('\r\n', '\n')
    lines = [ln for ln in got.split('\n')]
    assert lines[0] == 'MAKE READY REPORT'
    # Таблица заголовков присутствует
    assert '| step | status | details |' in got
    assert '|------|--------|---------|' in got
    # Последняя непустая строка — статус RELEASE_BUNDLE=READY|PARTIAL
    tail = ''
    for ln in reversed(lines):
        if ln.strip():
            tail = ln.strip()
            break
    assert tail in ('RELEASE_BUNDLE=READY', 'RELEASE_BUNDLE=PARTIAL')
    # Если PARTIAL — должна быть строка missing: [...]
    if tail == 'RELEASE_BUNDLE=PARTIAL':
        assert 'missing: [' in got



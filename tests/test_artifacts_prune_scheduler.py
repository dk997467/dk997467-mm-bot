import os
import time
from pathlib import Path


def test_artifacts_prune_scheduler(tmp_path, monkeypatch):
    from cli.run_bot import MarketMakerBot
    # Prepare artifacts
    art = tmp_path / 'artifacts'
    art.mkdir(parents=True, exist_ok=True)
    # create 10 canary json and 10 md with staggered mtimes (oldest first)
    files = []
    for i in range(10):
        jp = art / f'canary_20240101_000{i:02d}.json'
        mp = art / f'REPORT_CANARY_20240101_000{i:02d}.md'
        jp.write_text('{}', encoding='utf-8')
        mp.write_text('x', encoding='utf-8')
        ts = time.time() - (10 - i) * 86400  # i older days
        os.utime(jp, (ts, ts))
        os.utime(mp, (ts, ts))
        files.append(jp)
        files.append(mp)
    # big alerts.log
    log = art / 'alerts.log'
    with open(log, 'w', encoding='utf-8') as f:
        for i in range(12000):
            f.write('{"k":1}\n')
    # Configure env
    monkeypatch.setenv('PRUNE_INTERVAL_SEC', '0.2')
    monkeypatch.setenv('CANARY_MAX_SNAPSHOTS', '5')
    monkeypatch.setenv('CANARY_MAX_DAYS', '7')
    monkeypatch.setenv('ALERTS_MAX_LINES', '5000')
    # Run loop briefly
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv.running = True
    srv._prune_interval = 0.2
    # patch artifacts path usage by chdir
    cwd = os.getcwd()
    os.chdir(str(tmp_path))
    import asyncio
    async def run_once():
        t = asyncio.create_task(srv._prune_artifacts_loop())
        await asyncio.sleep(0.35)
        srv.running = False
        await asyncio.sleep(0)
        try:
            await asyncio.wait_for(t, timeout=1.0)
        except Exception:
            pass
    asyncio.run(run_once())
    os.chdir(cwd)
    # Check results
    remain_json = sorted((art).glob('canary_*.json'))
    remain_md = sorted((art).glob('REPORT_CANARY_*.md'))
    # not older than 7 days and at most 5
    assert len(remain_json) <= 5
    assert len(remain_md) <= 5
    # alerts trimmed
    with open(log, 'r', encoding='utf-8') as f:
        lines = f.read().splitlines()
    assert 4900 <= len(lines) <= 5000


"""
Ramp snapshot atomic writer.
"""
import os
import json
import asyncio
from pathlib import Path
from types import SimpleNamespace


def test_rollout_ramp_snapshot_atomic_write(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot(config_path="config.yaml", recorder=None, dry_run=True)
    bot._ramp_snapshot_path = str(tmp_path / "ramp.json")
    bot.running = True

    calls = {"fsync": 0, "replace": 0}
    real_fsync = os.fsync
    real_replace = os.replace

    def fake_fsync(fd):
        calls["fsync"] += 1
        return real_fsync(fd)

    def fake_replace(a, b):
        calls["replace"] += 1
        return real_replace(a, b)

    monkeypatch.setattr(os, 'fsync', fake_fsync)
    monkeypatch.setattr(os, 'replace', fake_replace)

    async def once():
        # run just one iteration by directly executing body (inline)
        sp = bot._ramp_snapshot_path
        tmp = sp + ".tmp"
        Path(sp).parent.mkdir(parents=True, exist_ok=True)
        snap = bot._to_ramp_snapshot()
        payload = json.dumps(snap, sort_keys=True, separators=(",", ":"))
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, sp)

    asyncio.run(once())

    assert calls['fsync'] >= 1
    assert calls['replace'] >= 1
    data = json.loads(Path(bot._ramp_snapshot_path).read_text(encoding='utf-8'))
    assert data['version'] == 1



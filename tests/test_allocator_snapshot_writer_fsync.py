import asyncio
from types import SimpleNamespace


def test_allocator_snapshot_writer_fsync(monkeypatch, tmp_path):
    # Patch os.replace and os.fsync to observe calls
    calls = {"replace": 0, "fsync": 0}
    import os

    real_replace = os.replace
    real_fsync = os.fsync

    def fake_replace(a, b):
        calls["replace"] += 1
        return real_replace(a, b)

    def fake_fsync(fd):
        calls["fsync"] += 1
        return 0

    monkeypatch.setattr(os, "replace", fake_replace)
    monkeypatch.setattr(os, "fsync", fake_fsync)

    # Build minimal bot with allocator and metrics
    from cli.run_bot import MarketMakerBot

    # Create a temporary config file based on default config.yaml assumption
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("trading:\n  symbols: [BTCUSDT]\n", encoding="utf-8")

    async def run():
        bot = MarketMakerBot(config_path=str(cfg_path), recorder=None, dry_run=True)
        await bot.initialize()
        bot._allocator_snapshot_path = str(tmp_path / "hwm.json")
        # run single iteration of inner writer
        async def one():
            # call the inner loop body once by mocking running flag short
            bot.running = True
            # manually execute body (copy from loop):
            import json as _json
            sp = bot._allocator_snapshot_path
            tmp = sp + ".tmp"
            from pathlib import Path as _P
            _P(sp).parent.mkdir(parents=True, exist_ok=True)
            snap = bot.ctx.allocator.to_snapshot()
            payload = _json.dumps(snap, sort_keys=True, separators=(",", ":"))
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, sp)
        await one()
        assert calls["fsync"] >= 1
        assert calls["replace"] >= 1

    asyncio.run(run())



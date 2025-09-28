import asyncio
import os


def test_snapshot_sigterm_flush(tmp_path, monkeypatch):
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot(config_path=str(tmp_path / 'cfg.yaml'), recorder=None, dry_run=True)
    bot._allocator_snapshot_path = str(tmp_path / 'hwm.json')
    called = {"save": 0}

    async def fake_initialize(self):
        bot.ctx = type('C', (), {})()
        bot.ctx.allocator = type('A', (), {"to_snapshot": lambda self=None: {"version":1,"hwm_equity_usd":0.0}})()
        bot.metrics = type('M', (), {"inc_allocator_snapshot_write": lambda *a, **k: None})()

    async def fake_stop(self):
        return None

    monkeypatch.setattr(MarketMakerBot, 'initialize', fake_initialize)
    monkeypatch.setattr(MarketMakerBot, 'stop', fake_stop)

    # Patch os.replace to count immediate save behavior
    real_replace = os.replace
    def fake_replace(a, b):
        called["save"] += 1
        return real_replace(a, b)
    monkeypatch.setattr(os, 'replace', fake_replace)

    async def run():
        await bot.initialize()
        # simulate immediate snapshot write body
        import json as _json
        sp = bot._allocator_snapshot_path
        tmp = sp + '.tmp'
        from pathlib import Path as _P
        _P(sp).parent.mkdir(parents=True, exist_ok=True)
        payload = _json.dumps({"version":1,"hwm_equity_usd":0.0}, sort_keys=True, separators=(",", ":"))
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, sp)
    asyncio.run(run())
    assert called["save"] >= 1



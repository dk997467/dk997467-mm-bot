import os
import json
import asyncio


async def _start_bot_on_port(bot, port):
    # minimal start of web server only
    bot.config = type("Cfg", (), {"monitoring": type("M", (), {"health_port": port})})()
    # stub data_recorder to avoid attribute errors
    class _DR:
        async def record_custom_event(self, *args, **kwargs):
            return None
    bot.data_recorder = _DR()
    await bot._start_web_server()


def test_admin_loader_size_limit_uniform(tmp_path, monkeypatch):
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot.metrics = type("M", (), {
        "inc_admin_request": lambda self,e: None,
        "inc_admin_unauthorized": lambda self,e: None,
        "inc_allocator_snapshot_load": lambda self,ok,ts: None,
        "inc_throttle_snapshot_load": lambda self,ok,ts: None,
        "inc_ramp_snapshot_load": lambda self,ok,ts: None,
        "inc_rollout_state_snapshot_load": lambda self,ok,ts: None,
    })()
    # stub context objects used by loaders
    class _Alloc:
        def load_snapshot(self, snap):
            return None
        def to_snapshot(self):
            return {"version":1}
    class _Throttle:
        def load_snapshot(self, snap):
            return None
        def to_snapshot(self):
            return {"version":1}
    bot.ctx = type("Ctx", (), {"allocator": _Alloc(), "throttle": _Throttle()})()
    os.environ['ADMIN_TOKEN'] = 'TOK'

    # create >1MB file
    big = tmp_path / "big.json"
    payload = {"version": 1, "data": "X" * (1024 * 1024 + 10)}
    with open(big, 'w', encoding='utf-8') as f:
        f.write(json.dumps(payload))

    async def run():
        await _start_bot_on_port(bot, 18995)
        import aiohttp
        headers = {"X-Admin-Token": "TOK"}
        async with aiohttp.ClientSession() as s:
            for path in [
                "/admin/allocator/load",
                "/admin/throttle/load",
                "/admin/rollout/ramp/load",
                "/admin/rollout/state/load",
            ]:
                body = {"path": str(big)}
                async with s.post(f"http://localhost:18995{path}", json=body, headers=headers) as r:
                    assert r.status == 400
                    j = await r.json()
                    assert "error" in j
    asyncio.run(run())


import asyncio


def test_admin_rate_limit_unified(monkeypatch):
    from cli.run_bot import MarketMakerBot
    import aiohttp, os
    os.environ['ADMIN_TOKEN'] = 'TOK'
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot.config = type("Cfg", (), {"monitoring": type("M", (), {"health_port": 18997})})()
    class _DR:
        async def record_custom_event(self, *a, **k): return None
    bot.data_recorder = _DR()

    async def run():
        await bot._start_web_server()
        headers = {"X-Admin-Token": "TOK"}
        async with aiohttp.ClientSession() as s:
            # choose mutating endpoints
            for path in ["/admin/audit/clear", "/admin/rollout"]:
                # POST many times to exceed 60/60s
                for i in range(65):
                    if path == "/admin/rollout":
                        payload = {"traffic_split_pct": 10}
                    else:
                        payload = {}
                    async with s.post(f"http://localhost:18997{path}", json=payload, headers=headers) as r:
                        if i < 60:
                            assert r.status in (200, 400)
                        else:
                            assert r.status == 429
    asyncio.run(run())


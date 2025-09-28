import asyncio


def test_admin_deterministic_json_errors(tmp_path):
    from cli.run_bot import MarketMakerBot
    import aiohttp
    import os

    os.environ['ADMIN_TOKEN'] = 'TOK'
    bot = MarketMakerBot.__new__(MarketMakerBot)
    # minimal cfg and recorder stub
    bot.config = type("Cfg", (), {"monitoring": type("M", (), {"health_port": 18996})})()
    class _DR:
        async def record_custom_event(self, *a, **k): return None
    bot.data_recorder = _DR()

    async def run():
        await bot._start_web_server()
        headers_bad = {"X-Admin-Token": "BAD"}
        headers_none = {}
        async with aiohttp.ClientSession() as s:
            # unauthorized (401)
            async with s.get('http://localhost:18996/admin/rollout', headers=headers_bad) as r1:
                b1 = await r1.read()
            async with s.get('http://localhost:18996/admin/rollout', headers=headers_none) as r2:
                b2 = await r2.read()
            assert r1.status == 401 and r2.status == 401 and b1 == b2
            # rate-limited (429) parity
            headers = {"X-Admin-Token":"TOK"}
            # drive up rate-limit
            for i in range(60):
                async with s.post('http://localhost:18996/admin/audit/clear', json={}, headers=headers) as _:
                    pass
            async with s.post('http://localhost:18996/admin/audit/clear', json={}, headers=headers) as r3:
                b3 = await r3.read()
            async with s.post('http://localhost:18996/admin/audit/clear', json={}, headers=headers) as r4:
                b4 = await r4.read()
            assert r3.status == 429 and r4.status == 429 and b3 == b4
    asyncio.run(run())


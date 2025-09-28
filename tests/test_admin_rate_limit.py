import asyncio
import os


def test_admin_rate_limit(monkeypatch):
    async def main():
        os.environ['ADMIN_TOKEN'] = 'TT'
        from cli.run_bot import MarketMakerBot
        from types import SimpleNamespace
        bot = MarketMakerBot.__new__(MarketMakerBot)
        bot.metrics = SimpleNamespace(inc_admin_request=lambda e: None, inc_admin_unauthorized=lambda e: None,
                                      inc_admin_rate_limited=lambda e: None, inc_admin_audit_event=lambda e: None)
        bot.config = SimpleNamespace(monitoring=SimpleNamespace(health_port=18992))
        await MarketMakerBot._start_web_server(bot)
        # tighten limits for test
        bot._admin_rl_window_sec = 60
        bot._admin_rl_limit = 2
        import aiohttp
        headers = {"X-Admin-Token": "TT"}
        async with aiohttp.ClientSession() as sess:
            # first allowed
            r1 = await sess.get('http://127.0.0.1:18992/admin/rollout', headers=headers)
            # second allowed
            r2 = await sess.get('http://127.0.0.1:18992/admin/rollout', headers=headers)
            # third should be rate-limited
            r3 = await sess.get('http://127.0.0.1:18992/admin/rollout', headers=headers)
            assert r3.status == 429
        await bot.web_runner.cleanup()
    asyncio.run(main())



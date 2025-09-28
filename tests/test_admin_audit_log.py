import asyncio
import os


def test_admin_audit_log(monkeypatch):
    async def main():
        os.environ['ADMIN_TOKEN'] = 'T'
        from cli.run_bot import MarketMakerBot
        from types import SimpleNamespace
        # Construct minimal bot and stub deps
        bot = MarketMakerBot.__new__(MarketMakerBot)
        bot.metrics = SimpleNamespace(inc_admin_request=lambda e: None, inc_admin_unauthorized=lambda e: None,
                                      inc_admin_rate_limited=lambda e: None, inc_admin_audit_event=lambda e: None)
        bot.config = SimpleNamespace(monitoring=SimpleNamespace(health_port=18991))
        class _Rec:
            async def record_custom_event(self, *a, **k):
                return None
        bot.data_recorder = _Rec()
        await MarketMakerBot._start_web_server(bot)
        import aiohttp
        headers = {"X-Admin-Token": "T"}
        async with aiohttp.ClientSession() as sess:
            # clear first
            async with sess.post('http://127.0.0.1:18991/admin/audit/clear', headers=headers) as resp:
                assert resp.status == 200
            # perform one GET rollout to be logged
            async with sess.get('http://127.0.0.1:18991/admin/rollout', headers=headers) as resp:
                assert resp.status in (200, 500)
            # read audit
            async with sess.get('http://127.0.0.1:18991/admin/audit/log', headers=headers) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert isinstance(data, list)
                assert any(item.get('endpoint') == '/admin/rollout' for item in data)
                for it in data:
                    assert 'ts' in it and 'actor' in it and 'payload_hash' in it
        await bot.web_runner.cleanup()
    asyncio.run(main())



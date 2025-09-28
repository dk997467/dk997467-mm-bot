import asyncio
import os


def test_admin_rollout_state_handlers(monkeypatch, tmp_path):
    os.environ['ADMIN_TOKEN'] = 'TOK'
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot.metrics = SimpleNamespace(inc_admin_request=lambda e: None, inc_admin_unauthorized=lambda e: None,
                                  inc_rollout_state_snapshot_load=lambda ok, ts: None,
                                  inc_rollout_state_snapshot_write=lambda ok, ts: None)
    bot.config = SimpleNamespace(monitoring=SimpleNamespace(health_port=18993),
                                 rollout=SimpleNamespace(traffic_split_pct=10, active='blue', salt='s', pinned_cids_green=[]),
                                 rollout_ramp=SimpleNamespace(enabled=False, steps_pct=[0,5,10], step_interval_sec=600, max_reject_rate_delta_pct=2.0, max_latency_delta_ms=50, max_pnl_delta_usd=0.0))
    async def run():
        await MarketMakerBot._start_web_server(bot)
        bot._rollout_state_snapshot_path = str(tmp_path / 'state.json')
        import aiohttp
        headers = {"X-Admin-Token": "TOK"}
        async with aiohttp.ClientSession() as sess:
            # snapshot
            async with sess.get('http://localhost:18993/admin/rollout/state/snapshot', headers=headers) as r:
                assert r.status == 200
                j = await r.json()
                assert j.get('version') == 1
            # load
            async with sess.post('http://localhost:18993/admin/rollout/state/load', json={"version":1,"traffic_split_pct":30}, headers=headers) as r:
                assert r.status == 200
            # status
            async with sess.get('http://localhost:18993/admin/rollout/state/snapshot_status', headers=headers) as r:
                assert r.status == 200
                j = await r.json()
                assert 'path' in j
    asyncio.run(run())


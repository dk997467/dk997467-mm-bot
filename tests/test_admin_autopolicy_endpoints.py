import asyncio
from types import SimpleNamespace
from aiohttp import web

from src.guards.autopolicy import AutoPolicy


class _App:
    def __init__(self):
        self.config = SimpleNamespace(
            autopolicy=SimpleNamespace(trigger_backoff_ms=3000.0, trigger_events_total=40, max_level=3)
        )
        self.ctx = SimpleNamespace(autopolicy=AutoPolicy(self.config.autopolicy))
        self.ctx.autopolicy.set_base(1000, 5, 10)
        self.metrics = SimpleNamespace(
            autopolicy_active=SimpleNamespace(set=lambda v: None),
            autopolicy_level=SimpleNamespace(set=lambda v: None),
            autopolicy_steps_total=SimpleNamespace(inc=lambda : None),
            autopolicy_last_change_ts=SimpleNamespace(set=lambda v: None),
            autopolicy_min_time_in_book_ms_eff=SimpleNamespace(set=lambda v: None),
            autopolicy_replace_threshold_bps_eff=SimpleNamespace(set=lambda v: None),
            autopolicy_levels_per_side_max_eff=SimpleNamespace(set=lambda v: None),
        )
        self.web_app = web.Application()

    async def _admin_autopolicy(self, request):
        # Minimal handler replica for test
        ap = self.ctx.autopolicy
        if request.method == 'GET':
            snap = ap.to_snapshot()
            eff = {
                "min_time_in_book_ms": float(snap.get("_overrides", {}).get("min_time_in_book_ms_eff", 0.0)),
                "replace_threshold_bps": float(snap.get("_overrides", {}).get("replace_threshold_bps_eff", 0.0)),
                "levels_per_side_max": float(snap.get("_overrides", {}).get("levels_per_side_max_eff", 0.0)),
            }
            resp = {
                "level": int(snap.get("level", 0)),
                "active": 1 if int(snap.get("level", 0)) > 0 else 0,
                "last_change_ts": float(snap.get("_last_change_ts", 0.0)),
                "effective": eff,
                "cfg_excerpt": {
                    "trigger_backoff_ms": float(self.config.autopolicy.trigger_backoff_ms),
                    "trigger_events_total": int(self.config.autopolicy.trigger_events_total),
                    "max_level": int(self.config.autopolicy.max_level),
                },
            }
            return web.json_response(resp)
        else:
            body = await request.json()
            if 'level' in body:
                self.ctx.autopolicy.level = int(body['level'])
                self.ctx.autopolicy.apply()
                self.metrics.autopolicy_steps_total.inc()
                return web.json_response({"status": "ok"})
            if 'reset' in body:
                self.ctx.autopolicy.level = 0
                self.ctx.autopolicy.apply()
                self.metrics.autopolicy_steps_total.inc()
                return web.json_response({"status": "ok"})
            return web.json_response({"status": "noop"})


async def _run_server(app:_App):
    app.web_app.router.add_get('/admin/autopolicy', app._admin_autopolicy)
    app.web_app.router.add_post('/admin/autopolicy', app._admin_autopolicy)
    runner = web.AppRunner(app.web_app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 18999)
    await site.start()
    return runner


def test_admin_autopolicy_endpoints():
    async def main():
        app = _App()
        runner = await _run_server(app)
        import aiohttp
        async with aiohttp.ClientSession() as sess:
            # GET
            async with sess.get('http://127.0.0.1:18999/admin/autopolicy') as resp:
                assert resp.status == 200
                data = await resp.json()
                assert 'level' in data and 'effective' in data
            # POST level=2
            async with sess.post('http://127.0.0.1:18999/admin/autopolicy', json={"level": 2}) as resp:
                assert resp.status == 200
            # POST reset
            async with sess.post('http://127.0.0.1:18999/admin/autopolicy', json={"reset": True}) as resp:
                assert resp.status == 200
        await runner.cleanup()
    asyncio.run(main())


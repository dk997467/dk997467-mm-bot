import asyncio
import json


async def _call(handler, method='GET', body=None, token='t'):
    class Req:
        headers = {"X-Admin-Token": token}
        rel_url = type("U", (), {"query": {}})()
        pass
    req = Req()
    req.method = method
    if body is not None:
        async def json_body():
            return body
        req.json = json_body  # type: ignore[attr-defined]
    return await handler(req)


def test_scheduler_apply_hotreload():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda r: True
    srv._admin_rate_limit_check = lambda a, e: True
    class DummySched:
        def __init__(self):
            self.windows = []
        def set_windows(self, w):
            self.windows = w
    srv.ctx = SimpleNamespace(scheduler=DummySched())
    loop = asyncio.new_event_loop()
    wins = [{"start":"08:00","end":"10:00"},{"start":"10:00","end":"12:00"}]
    res = loop.run_until_complete(_call(srv._admin_scheduler_apply, 'POST', {"windows": wins}))
    assert res.status == 200
    d = json.loads(res.text)
    assert d['applied'] == 2
    assert len(srv.ctx.scheduler.windows) == 2
    loop.close()


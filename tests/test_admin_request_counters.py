import asyncio
from types import SimpleNamespace


class _Req:
    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query = query or {}


class _M:
    def __init__(self):
        self.req = {}
        self.una = {}
    def get_portfolio_metrics_snapshot(self):
        return {"allocator_last_write_ts": 0.0, "allocator_last_load_ts": 0.0}
    def admin_requests_total(self): pass
    def admin_unauthorized_total(self): pass
    def inc_admin_request(self, endpoint: str):
        self.req[endpoint] = self.req.get(endpoint, 0) + 1
    def inc_admin_unauthorized(self, endpoint: str):
        self.una[endpoint] = self.una.get(endpoint, 0) + 1


class _App:
    def __init__(self):
        self.metrics = _M()
        self._allocator_snapshot_path = 'artifacts/allocator_hwm.json'
        self.ctx = SimpleNamespace(allocator=SimpleNamespace(to_snapshot=lambda: {"version":1,"hwm_equity_usd":0.0}))
    def _check_admin_token(self, req):
        return 'X-Admin-Token' in req.headers and req.headers['X-Admin-Token'] == 'ok'
    async def _admin_allocator_snapshot(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_allocator_snapshot(self, req)  # type: ignore
    async def _admin_allocator_snapshot_status(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_allocator_snapshot_status(self, req)  # type: ignore


def test_admin_request_counters():
    app = _App()
    async def run():
        # unauthorized
        r1 = await app._admin_allocator_snapshot(_Req())
        assert r1.status == 401
        assert app.metrics.una.get('/admin/allocator/snapshot', 0) == 1
        # authorized
        r2 = await app._admin_allocator_snapshot_status(_Req(headers={'X-Admin-Token': 'ok'}))
        assert r2.status == 200
        assert app.metrics.req.get('/admin/allocator/snapshot_status', 0) == 1
    asyncio.run(run())



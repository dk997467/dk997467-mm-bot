import asyncio
import os


class _Req:
    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query = query or {}


class _App:
    def __init__(self):
        from types import SimpleNamespace
        self.ctx = SimpleNamespace(allocator=None)
        # minimal metrics for status endpoint
        class _M:
            def get_portfolio_metrics_snapshot(self):
                return {"allocator_last_write_ts": 0.0, "allocator_last_load_ts": 0.0}
        self.metrics = _M()
    def _check_admin_token(self, req):
        import hmac, os
        token = os.getenv('ADMIN_TOKEN')
        if not token:
            return True
        provided = req.headers.get('X-Admin-Token') or req.query.get('token')
        if not provided:
            return False
        return hmac.compare_digest(str(provided), str(token))

    async def _admin_allocator_snapshot(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_allocator_snapshot(self, req)  # type: ignore

    async def _admin_allocator_snapshot_status(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_allocator_snapshot_status(self, req)  # type: ignore


def test_admin_token_auth(monkeypatch):
    os.environ['ADMIN_TOKEN'] = 'secret'
    app = _App()

    async def run():
        # no token
        r1 = await app._admin_allocator_snapshot(_Req())
        assert r1.status == 401
        # wrong token
        r2 = await app._admin_allocator_snapshot(_Req(headers={'X-Admin-Token': 'bad'}))
        assert r2.status == 401
        # correct token
        r3 = await app._admin_allocator_snapshot_status(_Req(headers={'X-Admin-Token': 'secret'}))
        assert r3.status == 200
    asyncio.run(run())



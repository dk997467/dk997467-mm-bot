"""
Admin handlers test for throttle snapshot endpoints.
"""
import asyncio
import json
from types import SimpleNamespace


class _App:
    def __init__(self, throttle, metrics=None):
        self.ctx = SimpleNamespace(throttle=throttle)
        self.metrics = metrics

    async def _admin_throttle_snapshot(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_throttle_snapshot(self, req)  # type: ignore

    async def _admin_throttle_load(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_throttle_load(self, req)  # type: ignore

    async def _admin_throttle_reset(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_throttle_reset(self, req)  # type: ignore

    async def _admin_throttle_snapshot_status(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_throttle_snapshot_status(self, req)  # type: ignore


class _Req:
    def __init__(self, body=None):
        self._body = body
        self.headers = {}
        self.query = {}
    async def json(self):
        return self._body if self._body is not None else {}


def test_throttle_admin_handlers():
    from src.guards.throttle import ThrottleGuard
    from src.common.config import ThrottleConfig
    tg = ThrottleGuard(ThrottleConfig())
    app = _App(tg, metrics=None)

    async def run():
        # Snapshot returns JSON with version
        resp = await app._admin_throttle_snapshot(_Req())
        assert resp.status == 200
        snap = json.loads(resp.body)
        assert snap.get("version") == 1

        # Load accepts snapshot
        resp2 = await app._admin_throttle_load(_Req(snap))
        assert resp2.status == 200
        body = json.loads(resp2.body)
        assert body.get("status") in ("ok", "failed")

        # Reset works
        resp3 = await app._admin_throttle_reset(_Req())
        assert resp3.status == 200

        # Status returns path and timestamps
        app._throttle_snapshot_path = "artifacts/throttle_snapshot.json"
        resp4 = await app._admin_throttle_snapshot_status(_Req())
        assert resp4.status == 200
        data = json.loads(resp4.body)
        assert "path" in data
        assert "last_write_ts" in data
        assert "last_load_ts" in data

    asyncio.run(run())



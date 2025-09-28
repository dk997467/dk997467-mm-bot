"""
Admin rollout split endpoints.
"""
import asyncio
import json
from types import SimpleNamespace


class _App:
    def __init__(self, cfg, metrics=None):
        self.config = cfg
        self.metrics = metrics

    async def _admin_rollout(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_rollout(self, req)  # type: ignore


class _Req:
    def __init__(self, body=None):
        self._body = body
        self.headers = {}
        self.query = {}
        self.method = 'GET' if body is None else 'POST'
    async def json(self):
        return self._body if self._body is not None else {}


def test_admin_rollout_split_get_post():
    cfg = SimpleNamespace(rollout=SimpleNamespace(traffic_split_pct=0, active='blue'))
    app = _App(cfg, metrics=SimpleNamespace(set_rollout_split_pct=lambda v: None, inc_admin_request=lambda ep: None, inc_admin_unauthorized=lambda ep: None))

    async def run():
        # GET current
        resp = await app._admin_rollout(_Req())
        assert resp.status == 200
        data = json.loads(resp.body)
        assert data['traffic_split_pct'] == 0
        assert data['active'] == 'blue'

        # POST update split
        resp2 = await app._admin_rollout(_Req({"traffic_split_pct": 45}))
        assert resp2.status == 200
        data2 = json.loads(resp2.body)
        assert data2['traffic_split_pct'] == 45
        # POST update active
        resp3 = await app._admin_rollout(_Req({"active": "green"}))
        assert resp3.status == 200
        data3 = json.loads(resp3.body)
        assert data3['active'] == 'green'
        # invalid split
        resp4 = await app._admin_rollout(_Req({"traffic_split_pct": 101}))
        assert resp4.status == 400
    asyncio.run(run())



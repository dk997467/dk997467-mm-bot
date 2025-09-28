"""
Admin update salt and pinned CIDs.
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


def test_admin_rollout_pins_and_salt():
    cfg = SimpleNamespace(rollout=SimpleNamespace(traffic_split_pct=0, active='blue', salt='S', pinned_cids_green=[]))
    metrics = SimpleNamespace(set_rollout_split_pct=lambda v: None, inc_admin_request=lambda ep: None, inc_admin_unauthorized=lambda ep: None)
    app = _App(cfg, metrics)

    async def run():
        # POST salt and pinned list via CSV
        r = await app._admin_rollout(_Req({"salt": "NEW_SALT", "pinned_cids_green": "A,B,C"}))
        assert r.status == 200
        d = json.loads(r.body)
        assert d['salt'] == 'NEW_SALT'
        assert d['pinned_cids_green'] == ['A','B','C']
        # GET reflects values
        g = await app._admin_rollout(_Req())
        gd = json.loads(g.body)
        assert gd['salt'] == 'NEW_SALT'
        assert gd['pinned_cids_green'] == ['A','B','C']
    asyncio.run(run())



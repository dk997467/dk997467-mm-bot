"""
Admin rollout ramp endpoint test.
"""
import asyncio
import json
from types import SimpleNamespace


class _App:
    def __init__(self, cfg, metrics=None):
        self.config = cfg
        self.metrics = metrics
        self._ramp_step_idx = 0
    async def _admin_rollout_ramp(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_rollout_ramp(self, req)  # type: ignore


class _Req:
    def __init__(self, body=None):
        self._body = body
        self.headers = {}
        self.query = {}
        self.method = 'GET' if body is None else 'POST'
    async def json(self):
        return self._body if self._body is not None else {}


def test_admin_rollout_ramp_endpoint():
    cfg = SimpleNamespace(rollout_ramp=SimpleNamespace(enabled=False, steps_pct=[0,10,20], step_interval_sec=600, max_reject_rate_delta_pct=2.0, max_latency_delta_ms=50, max_pnl_delta_usd=0.0))
    metrics = SimpleNamespace(set_ramp_enabled=lambda v: None, set_ramp_step_idx=lambda i: None, inc_admin_request=lambda ep: None, inc_admin_unauthorized=lambda ep: None)
    app = _App(cfg, metrics)

    async def run():
        # GET
        r1 = await app._admin_rollout_ramp(_Req())
        assert r1.status == 200
        d1 = json.loads(r1.body)
        assert 'enabled' in d1 and 'steps_pct' in d1
        # POST valid
        r2 = await app._admin_rollout_ramp(_Req({"enabled": True, "steps_pct": [0,5,10], "step_interval_sec": 30}))
        assert r2.status == 200
        d2 = json.loads(r2.body)
        assert d2['enabled'] is True
        assert d2['steps_pct'] == [0,5,10]
        # POST invalid steps
        r3 = await app._admin_rollout_ramp(_Req({"steps_pct": []}))
        assert r3.status == 400
        # POST invalid interval
        r4 = await app._admin_rollout_ramp(_Req({"step_interval_sec": 5}))
        assert r4.status == 400
    asyncio.run(run())



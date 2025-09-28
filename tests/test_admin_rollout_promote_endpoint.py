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


def test_admin_rollout_promote_endpoint():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._ramp_state = {"frozen": False, "consecutive_stable_steps": 0}
    srv._ramp_step_idx = 2
    srv._rollout_state_dirty = False
    srv.config = SimpleNamespace(
        rollout=SimpleNamespace(traffic_split_pct=50, active='blue', salt='s', blue={}, green={}),
        rollout_ramp=SimpleNamespace(enabled=True),
    )
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    class M:
        def __init__(self):
            self._vals = {}
        def set_ramp_enabled(self, v):
            self._vals['re'] = v
        def set_ramp_step_idx(self, v):
            self._vals['rs'] = v
        def set_rollout_split_pct(self, v):
            self._vals['sp'] = v
        def inc_autopromote_attempt(self):
            self._vals['att'] = self._vals.get('att', 0) + 1
        def inc_autopromote_flip(self):
            self._vals['flip'] = self._vals.get('flip', 0) + 1
    srv.metrics = M()
    loop = asyncio.new_event_loop()
    # Preview
    res = loop.run_until_complete(_call(srv._admin_rollout_promote, 'GET'))
    assert res.status == 200
    d = json.loads(res.text)
    assert d['preview']['active_new'] == 'green'
    # Apply
    res = loop.run_until_complete(_call(srv._admin_rollout_promote, 'POST', {}))
    assert res.status == 200
    d = json.loads(res.text)
    assert d['applied']['traffic_split_pct_new'] == 0
    assert srv.config.rollout.active == 'green'
    assert srv.config.rollout_ramp.enabled is False
    assert srv._ramp_step_idx == 0
    loop.close()


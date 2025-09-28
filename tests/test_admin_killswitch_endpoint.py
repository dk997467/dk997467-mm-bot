import json
import asyncio


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


def test_admin_killswitch_endpoint():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv.config = SimpleNamespace(killswitch=SimpleNamespace(enabled=False, dry_run=True, max_reject_delta=0.02, max_latency_delta_ms=50, min_fills=500, action='rollback'))
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    loop = asyncio.new_event_loop()
    # GET
    res = loop.run_until_complete(_call(srv._admin_killswitch, 'GET'))
    assert res.status == 200
    d = json.loads(res.text)
    assert set(d.keys()) == {"enabled","dry_run","max_reject_delta","max_latency_delta_ms","min_fills","action"}
    # POST valid
    res = loop.run_until_complete(_call(srv._admin_killswitch, 'POST', {"enabled": True, "dry_run": False, "max_reject_delta": 0.05, "max_latency_delta_ms": 60, "min_fills": 1000, "action": "freeze"}))
    assert res.status == 200
    d = json.loads(res.text)
    assert d["enabled"] is True and d["dry_run"] is False and d["action"] == "freeze" and d["min_fills"] == 1000
    # POST invalid action
    res = loop.run_until_complete(_call(srv._admin_killswitch, 'POST', {"action": "invalid"}))
    assert res.status == 400
    loop.close()



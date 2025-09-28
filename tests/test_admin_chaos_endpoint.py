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


def test_admin_chaos_endpoint():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv.config = SimpleNamespace(chaos=SimpleNamespace(enabled=False, reject_inflate_pct=0.0, latency_inflate_ms=0))
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True

    loop = asyncio.new_event_loop()
    # GET
    res = loop.run_until_complete(_call(srv._admin_chaos, 'GET'))
    assert res.status == 200
    d = json.loads(res.text)
    assert set(d.keys()) == {"enabled","reject_inflate_pct","latency_inflate_ms"}
    # POST valid
    res = loop.run_until_complete(_call(srv._admin_chaos, 'POST', {"enabled": True, "reject_inflate_pct": 0.5, "latency_inflate_ms": 100}))
    assert res.status == 200
    d = json.loads(res.text)
    assert d["enabled"] is True and d["reject_inflate_pct"] == 0.5 and d["latency_inflate_ms"] == 100
    # POST invalid
    res = loop.run_until_complete(_call(srv._admin_chaos, 'POST', {"reject_inflate_pct": 2.0}))
    assert res.status == 400
    loop.close()



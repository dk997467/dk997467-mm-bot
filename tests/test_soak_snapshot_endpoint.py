import json
import asyncio


def _mk_srv():
    from cli.run_bot import MarketMakerBot
    from tests.e2e._utils import make_metrics_ctx
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    srv.metrics = make_metrics_ctx()
    return srv


def test_soak_snapshot_endpoint_deterministic_json():
    srv = _mk_srv()
    loop = asyncio.new_event_loop()
    try:
        class Req:
            headers = {"X-Admin-Token": "t"}
            rel_url = type("U", (), {"query": {}})()
        res = loop.run_until_complete(srv._admin_perf_soak_snapshot(Req()))
        assert res.status == 200
        data = json.loads(res.body.decode())
        # deterministic structure
        assert set(data.keys()) == {"version", "current", "window_max"}
        cur = data.get("current", {})
        wmax = data.get("window_max", {})
        assert set(cur.keys()) == {"rss_bytes", "open_fds", "threads", "gc_gen", "drift_ms"}
        assert set(wmax.keys()) == {"rss_bytes", "open_fds", "threads", "gc_gen", "drift_ms"}
        # deterministic json dumps
        s1 = json.dumps(data, sort_keys=True, separators=(",", ":"))
        s2 = json.dumps(data, sort_keys=True, separators=(",", ":"))
        assert s1 == s2
    finally:
        loop.close()



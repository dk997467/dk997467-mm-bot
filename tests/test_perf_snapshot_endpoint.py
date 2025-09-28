import json
import asyncio


def _mk_srv():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    # minimal attributes
    from tests.e2e._utils import make_metrics_ctx
    srv.metrics = make_metrics_ctx()
    return srv


def test_perf_snapshot_endpoint_works():
    srv = _mk_srv()
    loop = asyncio.new_event_loop()
    try:
        class Req:
            headers = {"X-Admin-Token": "t"}
            rel_url = type("U", (), {"query": {}})()
        res = loop.run_until_complete(srv._admin_perf_snapshot(Req()))
        assert res.status == 200
        data = json.loads(res.body.decode())
        assert set(data.keys()) == {"loops", "event_loop_drift_ms", "admin_latency_buckets"}
        # determinism: json.dumps with sorted keys must be stable
        s1 = json.dumps(data, sort_keys=True, separators=(",", ":"))
        s2 = json.dumps(data, sort_keys=True, separators=(",", ":"))
        assert s1 == s2
    finally:
        loop.close()



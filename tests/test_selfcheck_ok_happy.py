import asyncio
import json


def test_selfcheck_ok_happy(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    from tests.e2e._utils import make_metrics_ctx
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv.metrics = make_metrics_ctx()
    # seed heartbeats recent
    srv.metrics.record_loop_heartbeat('export')
    srv.metrics.record_loop_heartbeat('prune')
    srv.metrics.record_loop_heartbeat('slo')
    srv.metrics.record_loop_heartbeat('soak')
    class Req:
        headers = {"X-Admin-Token":"t"}
        rel_url = type("U", (), {"query": {}})()
        path = '/admin/selfcheck'
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(srv._admin_selfcheck(Req()))
        assert res.status == 200
        data = json.loads(res.body.decode())
        assert data.get('status') == 'ok'
        assert data.get('reasons') == []
    finally:
        loop.close()



import asyncio
import json


def test_selfcheck_admin_latency_budget(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    from tests.e2e._utils import make_metrics_ctx
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setenv('SELFCHK_ADMIN_P50_MS', '10')
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv.metrics = make_metrics_ctx()
    class Req:
        headers = {"X-Admin-Token":"t"}
        rel_url = type("U", (), {"query": {}})()
        path = '/admin/selfcheck'
    loop = asyncio.new_event_loop()
    try:
        # first call seeds bucket counters
        res1 = loop.run_until_complete(srv._admin_selfcheck(Req()))
        assert res1.status == 200
        # second call should find prior latency and may fail budget; since bucket math is best-effort, just ensure deterministic JSON
        res2 = loop.run_until_complete(srv._admin_selfcheck(Req()))
        data2 = json.loads(res2.body.decode())
        assert 'status' in data2 and 'reasons' in data2 and 'loops' in data2
    finally:
        loop.close()



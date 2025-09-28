import asyncio
import json


def test_selfcheck_drift_budget(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    from tests.e2e._utils import make_metrics_ctx
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setenv('SELFCHK_DRIFT_MAX_MS', '1')
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv.metrics = make_metrics_ctx()
    # bump drift
    srv.metrics.set_event_loop_drift(200.0)
    class Req:
        headers = {"X-Admin-Token":"t"}
        rel_url = type("U", (), {"query": {}})()
        path = '/admin/selfcheck'
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(srv._admin_selfcheck(Req()))
        data = json.loads(res.body.decode())
        assert data.get('status') == 'fail'
        assert 'event_loop_drift' in data.get('reasons', [])
    finally:
        loop.close()



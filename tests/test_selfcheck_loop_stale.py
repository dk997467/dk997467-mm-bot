import asyncio
import json


def test_selfcheck_loop_stale(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    from tests.e2e._utils import make_metrics_ctx
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setenv('SELFCHK_LOOP_MAX_AGE_SEC', '0')
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv.metrics = make_metrics_ctx()
    # heartbeat long ago by directly mutating internal state
    with srv.metrics._pm_lock:
        srv.metrics._loop_heartbeats['export'] = 0.0
    class Req:
        headers = {"X-Admin-Token":"t"}
        rel_url = type("U", (), {"query": {}})()
        path = '/admin/selfcheck'
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(srv._admin_selfcheck(Req()))
        data = json.loads(res.body.decode())
        assert data.get('status') == 'fail'
        assert 'loops_heartbeats_fresh' in data.get('reasons', [])
    finally:
        loop.close()



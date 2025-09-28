import asyncio
import json
import os
import stat


def test_selfcheck_artifacts_dir_ro(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    from tests.e2e._utils import make_metrics_ctx
    # make dir read-only
    artifacts = tmp_path / 'art'
    artifacts.mkdir()
    os.chmod(str(artifacts), stat.S_IREAD | stat.S_IEXEC)
    monkeypatch.setenv('ARTIFACTS_DIR', str(artifacts))
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
        res = loop.run_until_complete(srv._admin_selfcheck(Req()))
        data = json.loads(res.body.decode())
        assert data.get('status') == 'fail'
        assert 'artifacts_dir_write' in data.get('reasons', [])
    finally:
        loop.close()



import asyncio
import json


def _mk_srv(primary: str, secondary: str | None = None):
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = MarketMakerBot._check_admin_token.__get__(srv, MarketMakerBot)  # bind method
    # seed tokens directly
    srv._admin_token_primary = primary
    srv._admin_token_secondary = secondary or ''
    import threading
    srv._admin_token_lock = threading.Lock()
    # fake metrics ctx not needed here
    return srv


def test_admin_token_rotation_and_access(monkeypatch):
    srv = _mk_srv('p1', 's1')
    # access with primary
    class R:
        def __init__(self, tok):
            self.headers = {"X-Admin-Token": tok}
            self.rel_url = type("U", (), {"query": {}})()
            self.path = '/admin/test'
    assert srv._check_admin_token(R('p1')) is True
    assert srv._check_admin_token(R('s1')) is True
    assert srv._check_admin_token(R('bad')) is False

    # rotate via endpoint
    loop = asyncio.new_event_loop()
    try:
        async def call_rotate(body: dict):
            class Req:
                def __init__(self, b):
                    self._b = b
                    self.headers = {"X-Admin-Token": 'p1'}
                    self.rel_url = type("U", (), {"query": {}})()
                    self.path = '/admin/auth/rotate'
                async def json(self):
                    return self._b
            resp = await srv._admin_auth_rotate(Req(body))
            return json.loads(resp.body.decode())

        out = loop.run_until_complete(call_rotate({"primary": "p2", "secondary": "s2", "activate": "secondary"}))
        assert out.get('status') == 'ok'
        # new tokens should work
        assert srv._check_admin_token(R('p2')) is True
        assert srv._check_admin_token(R('s2')) is True
        # old tokens should fail
        assert srv._check_admin_token(R('p1')) is False
        assert srv._check_admin_token(R('s1')) is False
    finally:
        loop.close()



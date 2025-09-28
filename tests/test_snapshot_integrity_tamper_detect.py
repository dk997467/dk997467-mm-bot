import json


def test_snapshot_integrity_tamper_detect(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    # metrics stub with required counter
    class M:
        def __init__(self):
            self._cnt = {}
        def snapshot_integrity_fail_total(self, *a, **k):
            return self
        def labels(self, kind):
            self._cnt[kind] = self._cnt.get(kind, 0) + 1
            return SimpleNamespace(inc=lambda : None)
    srv.metrics = None  # metric increments are best-effort; we test HTTP 400

    # write valid wrapper
    p = tmp_path / 'allocator_hwm.json'
    srv._atomic_snapshot_write(str(p), {"version":1,"hwm_equity_usd":1.0}, version=1)
    # tamper one byte
    raw = p.read_bytes()
    tampered = raw[:-1] + (b'X' if raw[-1:] != b'X' else b'Y')
    p.write_bytes(tampered)

    # loader should detect bad checksum
    class Req:
        def __init__(self):
            self.headers = {"X-Admin-Token":"t"}
            self.rel_url = SimpleNamespace(query={})
        async def json(self):
            return {"path": str(p)}
        path = '/admin/allocator/load'

    from types import SimpleNamespace
    srv._check_admin_token = lambda req: True
    resp = __import__('asyncio').get_event_loop().run_until_complete(srv._admin_allocator_load(Req()))
    assert resp.status == 400
    body = json.loads(resp.body.decode())
    assert body.get('error') in ('bad_checksum','invalid_structure')



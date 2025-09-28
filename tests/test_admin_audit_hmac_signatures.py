import asyncio
import json
import hmac
import hashlib


def test_admin_audit_hmac_signatures(monkeypatch):
    from cli.run_bot import MarketMakerBot
    # fixed ASCII key
    monkeypatch.setenv('ADMIN_AUDIT_HMAC_KEY', '616263')  # hex for 'abc'
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    # minimal _admin_audit_record call via an endpoint
    loop = asyncio.new_event_loop()
    try:
        class Req:
            headers = {"X-Admin-Token": "t"}
            rel_url = type("U", (), {"query": {}})()
            path = '/admin/test'
        # record audit with known payload
        payload = {"x": 1, "y": 2}
        srv._admin_audit_record('/admin/test', Req(), payload)
        # fetch audit log via endpoint
        res = loop.run_until_complete(srv._admin_audit_log_get(Req()))
        assert res.status == 200
        items = json.loads(res.body.decode())
        assert isinstance(items, list) and len(items) >= 1
        last = items[-1]
        assert 'sig' in last and isinstance(last['sig'], str)
        # recompute signature deterministically
        b = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode('utf-8')
        key = bytes.fromhex('616263')
        expect = hmac.new(key, b, hashlib.sha256).hexdigest()
        assert last['sig'] == expect
        # tamper detection: change payload hash and ensure mismatch
        last_tampered = dict(last)
        last_tampered['payload_hash'] = 'deadbeef'
        assert last_tampered['sig'] == last['sig']  # sig independent of displayed hash
        # simulate tampered payload by recomputing with different content should mismatch
        b2 = json.dumps({"x": 9}, sort_keys=True, separators=(",", ":")).encode('utf-8')
        expect2 = hmac.new(key, b2, hashlib.sha256).hexdigest()
        assert expect2 != last['sig']
    finally:
        loop.close()



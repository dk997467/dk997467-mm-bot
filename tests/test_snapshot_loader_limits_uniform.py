import json


def test_snapshot_loader_limits_uniform(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    import os
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    # create big file >1MB
    big = tmp_path / 'big.json'
    big.write_bytes(b'{"payload":' + b'"A"'* (1024*1024) + b',"version":1,"sha256":"00"}')

    # Prepare requests for allocator/throttle/rollout_state/cost_calib
    class Req:
        def __init__(self, path, ep):
            self._body = {"path": path}
            self.headers = {"X-Admin-Token":"t"}
            self.rel_url = type("U", (), {"query": {}})()
            self.path = ep
        async def json(self):
            return self._body

    # Each should return 400 on too large
    loop = __import__('asyncio').new_event_loop()
    try:
        for ep in ('/admin/allocator/load','/admin/throttle/load','/admin/rollout/state/load','/admin/allocator/cost_calibration/load'):
            fn = getattr(srv, {'/admin/allocator/load':'_admin_allocator_load','/admin/throttle/load':'_admin_throttle_load','/admin/rollout/state/load':'_admin_rollout_state_load','/admin/allocator/cost_calibration/load':'_admin_cost_calibration_load'}[ep])
            resp = loop.run_until_complete(fn(Req(str(big), ep)))
            assert resp.status == 400
    finally:
        loop.close()



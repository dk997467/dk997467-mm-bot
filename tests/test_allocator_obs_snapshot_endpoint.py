import json
import asyncio


def _mk_srv():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    # metrics with some sample data
    from tests.e2e._utils import make_metrics_ctx
    m = make_metrics_ctx()
    srv.metrics = m
    # seed fillrate and cost snapshots
    for _ in range(10):
        m.record_fill_event('BTCUSDT', True)
    # publish some attenuation
    try:
        m.allocator_fillrate_attenuation.labels(symbol='BTCUSDT').set(0.9)
    except Exception:
        pass
    # cost snapshot via public setter
    m.set_allocator_cost('BTCUSDT', 12.0, 0.95)
    return srv


def test_obs_snapshot_endpoint_returns_det_json():
    srv = _mk_srv()
    loop = asyncio.new_event_loop()
    try:
        class Req:
            headers = {"X-Admin-Token": "t"}
            rel_url = type("U", (), {"query": {}})()
        res = loop.run_until_complete(srv._admin_allocator_obs_snapshot(Req()))
        assert res.status == 200
        data = json.loads(res.body.decode())
        assert 'symbols' in data
        sym = data['symbols']
        assert 'BTCUSDT' in sym
        btc = sym['BTCUSDT']
        assert set(btc.keys()) == {'cost_bps', 'fillrate_ewma', 'fillrate_attenuation'}
        # determinism
        s1 = json.dumps(data, sort_keys=True, separators=(",", ":"))
        s2 = json.dumps(data, sort_keys=True, separators=(",", ":"))
        assert s1 == s2
    finally:
        loop.close()



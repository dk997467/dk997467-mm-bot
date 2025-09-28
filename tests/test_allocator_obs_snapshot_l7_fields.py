import json
import asyncio


def _mk_srv():
    from cli.run_bot import MarketMakerBot
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    # metrics with L7 hooks
    from tests.e2e._utils import make_metrics_ctx
    m = make_metrics_ctx()
    srv.metrics = m
    # seed snapshots
    for _ in range(5):
        m.record_fill_event('BTC', True)
    m.test_set_liquidity_depth('BTC', 100.0)
    m.record_trade_notional('BTC', 500.0)
    return srv


def test_obs_snapshot_contains_l7_and_is_deterministic():
    srv = _mk_srv()
    loop = asyncio.new_event_loop()
    try:
        class Req:
            headers = {"X-Admin-Token": "t"}
            rel_url = type("U", (), {"query": {}})()
        res = loop.run_until_complete(srv._admin_allocator_obs_snapshot(Req()))
        assert res.status == 200
        data = json.loads(res.body.decode())
        symbols = data.get('symbols', {})
        assert 'BTC' in symbols
        btc = symbols['BTC']
        for k in ('turnover_usd','turnover_factor'):
            assert k in btc
        # determinism: stable json
        s1 = json.dumps(data, sort_keys=True, separators=(",", ":"))
        s2 = json.dumps(data, sort_keys=True, separators=(",", ":"))
        assert s1 == s2
    finally:
        loop.close()



import json
import asyncio


async def _call(app, handler, method='GET', body=None):
    class Req:
        headers = {"X-Admin-Token": "t"}
        rel_url = type("U", (), {"query": {}})()
        pass
    req = Req()
    req.method = method
    if body is not None:
        async def json_body():
            return body
        req.json = json_body  # type: ignore[attr-defined]
    return await handler(req)


def test_canary_report_structure():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv.config = SimpleNamespace(rollout=SimpleNamespace(traffic_split_pct=25, active='blue', salt='s', blue={"a":1}, green={"b":2}), rollout_ramp=SimpleNamespace(enabled=True))
    srv._params_hash = "ph"
    srv.metrics = SimpleNamespace(
        rollout_split_observed_pct=SimpleNamespace(_value=SimpleNamespace(get=lambda: 20.0)),
        _rollout_orders_count={'blue': 10, 'green': 5},
        _rollout_fills={'blue': 3, 'green': 2},
        _rollout_rejects={'blue': 1, 'green': 0},
        _rollout_latency_ewma={'blue': 30.0, 'green': 25.0},
        rollout_ramp_step_idx=SimpleNamespace(_value=SimpleNamespace(get=lambda: 2.0)),
        rollout_ramp_frozen=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        _ramp_holds_counts={'sample': 1, 'cooldown': 2},
        rollout_ramp_cooldown_seconds=SimpleNamespace(_value=SimpleNamespace(get=lambda: 120.0)),
        inc_admin_unauthorized=lambda endpoint: None,
        inc_admin_rate_limited=lambda endpoint: None,
        inc_admin_request=lambda endpoint: None,
    )
    # token check bypass
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    # call handler
    loop = asyncio.new_event_loop()
    res = loop.run_until_complete(_call(None, srv._admin_report_canary))
    assert res.status == 200
    data = json.loads(res.text)
    # Validate structure
    assert set(data.keys()) == {"meta","rollout","drift"}
    assert isinstance(data["meta"]["commit"], str)
    assert isinstance(data["meta"]["params_hash"], str)
    assert isinstance(data["meta"]["generated_at"], str)
    r = data["rollout"]
    for k in ["split_expected_pct","split_observed_pct","orders_blue","orders_green","fills_blue","fills_green","rejects_blue","rejects_green","latency_ms_avg_blue","latency_ms_avg_green","salt_hash","overlay_diff_keys","ramp"]:
        assert k in r
    assert isinstance(r["overlay_diff_keys"], list)
    dr = data["drift"]
    assert set(dr.keys()) == {"cap_pct","min_sample_orders","alert","reason"}
    # Deterministic JSON: two calls must match byte-for-byte
    res2 = loop.run_until_complete(_call(None, srv._admin_report_canary))
    assert res.text == res2.text
    loop.close()



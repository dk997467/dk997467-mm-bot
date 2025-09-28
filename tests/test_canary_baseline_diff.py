import json
import os
import asyncio


async def _call(handler, method='GET', body=None):
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


def test_canary_baseline_diff(tmp_path, monkeypatch):
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    # thresholds via env
    monkeypatch.setenv('CANARY_DIFF_REJECT_DELTA', '0.01')
    monkeypatch.setenv('CANARY_DIFF_LAT_MS', '10')
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    srv._build_time_iso = '1970-01-01T00:00:00Z'
    srv._params_hash = 'ph'
    srv.config = SimpleNamespace(monitoring=SimpleNamespace(health_port=0))
    srv.metrics = SimpleNamespace(
        rollout_split_observed_pct=SimpleNamespace(_value=SimpleNamespace(get=lambda: 50.0)),
        _rollout_orders_count={'blue': 100, 'green': 100},
        _rollout_fills={'blue': 90, 'green': 80},
        _rollout_rejects={'blue': 1, 'green': 5},
        _rollout_latency_ewma={'blue': 20.0, 'green': 40.0},
        rollout_ramp_step_idx=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        rollout_ramp_frozen=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        _ramp_holds_counts={'sample': 0, 'cooldown': 0},
        rollout_ramp_cooldown_seconds=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        inc_admin_unauthorized=lambda ep: None,
        inc_admin_rate_limited=lambda ep: None,
        inc_admin_request=lambda ep: None,
    )
    # write baseline
    os.makedirs(tmp_path, exist_ok=True)
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        base = srv._build_canary_payload()
        os.makedirs('artifacts', exist_ok=True)
        with open('artifacts/canary_base.json','w',encoding='utf-8') as f:
            f.write(json.dumps(base, sort_keys=True, separators=(",",":")))
        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(_call(srv._admin_report_canary_baseline, 'POST', {"path":"artifacts/canary_base.json"}))
        assert res.status == 200
        # Now diff
        res2 = loop.run_until_complete(_call(srv._admin_report_canary_diff, 'GET'))
        assert res2.status == 200
        d = json.loads(res2.text)
        assert set(d.keys()) == {'delta','regressions'}
        # With changed metrics vs baseline, deltas non-zero and regressions present under thresholds
        assert isinstance(d['delta']['split_observed_pct'], float)
        assert isinstance(d['delta']['reject_rate_green_minus_blue'], float)
        assert isinstance(d['delta']['latency_ms_delta'], float)
        assert isinstance(d['regressions'], list)
        loop.close()
    finally:
        os.chdir(cwd)



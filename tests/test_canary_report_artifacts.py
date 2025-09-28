import json
import os
import asyncio


async def _call(app, handler, method='POST', body=None):
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


def test_canary_report_artifacts(tmp_path):
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv.config = SimpleNamespace(rollout=SimpleNamespace(traffic_split_pct=50, active='blue', salt='xyz', blue={"a":1}, green={"a":1,"b":2}), rollout_ramp=SimpleNamespace(enabled=False))
    srv._params_hash = "ph2"
    srv.metrics = SimpleNamespace(
        rollout_split_observed_pct=SimpleNamespace(_value=SimpleNamespace(get=lambda: 55.0)),
        _rollout_orders_count={'blue': 100, 'green': 120},
        _rollout_fills={'blue': 60, 'green': 70},
        _rollout_rejects={'blue': 4, 'green': 5},
        _rollout_latency_ewma={'blue': 20.0, 'green': 22.0},
        rollout_ramp_step_idx=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        rollout_ramp_frozen=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        _ramp_holds_counts={'sample': 0, 'cooldown': 0},
        rollout_ramp_cooldown_seconds=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        inc_admin_unauthorized=lambda endpoint: None,
        inc_admin_rate_limited=lambda endpoint: None,
        inc_admin_request=lambda endpoint: None,
    )
    # place artifacts in tmp
    os.makedirs(tmp_path, exist_ok=True)
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    # monkeypatch paths via chdir
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        loop = asyncio.new_event_loop()
        res = loop.run_until_complete(_call(None, srv._admin_report_canary_generate, 'POST', {}))
        assert res.status == 200
        # Check files created
        cj = os.path.join(tmp_path, 'artifacts', 'canary.json')
        rm = os.path.join(tmp_path, 'artifacts', 'REPORT_CANARY.md')
        assert os.path.exists(cj)
        assert os.path.exists(rm)
        # Deterministic JSON
        s1 = open(cj, 'rb').read()
        s2 = open(cj, 'rb').read()
        assert s1 == s2
        # MD contains key fields
        md = open(rm, 'r', encoding='utf-8').read()
        assert 'E2 Canary Report' in md
        assert 'split_expected_pct' in md
        assert 'orders_blue' in md and 'orders_green' in md
        assert 'fills_blue' in md and 'fills_green' in md
        assert 'rejects_blue' in md and 'rejects_green' in md
    finally:
        os.chdir(cwd)
        try:
            loop.close()
        except Exception:
            pass



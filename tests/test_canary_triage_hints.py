import json
import asyncio


async def _call_get(handler):
    class Req:
        headers = {"X-Admin-Token": "t"}
        rel_url = type("U", (), {"query": {}})()
        method = 'GET'
    return await handler(Req())


def test_canary_triage_hints():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace

    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    # Config rollout and metrics
    srv.config = SimpleNamespace(rollout=SimpleNamespace(traffic_split_pct=40, active='blue', salt='salt', blue={}, green={}), rollout_ramp=SimpleNamespace(enabled=True))
    srv.metrics = SimpleNamespace(
        rollout_split_observed_pct=SimpleNamespace(_value=SimpleNamespace(get=lambda: 60.0)),
        _rollout_orders_count={'blue': 1000, 'green': 1000},
        _rollout_fills={'blue': 900, 'green': 800},
        _rollout_rejects={'blue': 10, 'green': 40},  # green reject rate higher
        _rollout_latency_ewma={'blue': 30.0, 'green': 90.5},  # +60.5 ms
        rollout_ramp_step_idx=SimpleNamespace(_value=SimpleNamespace(get=lambda: 3.0)),
        rollout_ramp_frozen=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        _ramp_holds_counts={'sample': 2, 'cooldown': 1},
        rollout_ramp_cooldown_seconds=SimpleNamespace(_value=SimpleNamespace(get=lambda: 45.0)),
        inc_admin_unauthorized=lambda endpoint: None,
        inc_admin_rate_limited=lambda endpoint: None,
        inc_admin_request=lambda endpoint: None,
    )

    loop = asyncio.new_event_loop()
    res = loop.run_until_complete(_call_get(srv._admin_report_canary))
    assert res.status == 200
    data = json.loads(res.text)
    assert 'hints' in data and isinstance(data['hints'], list)
    # Expected hints in deterministic order
    assert data['hints'] == [
        'green_rejects_spike',
        'green_latency_regression',
        'split_drift_exceeds_cap',
        'ramp_hold_low_sample',
        'ramp_on_cooldown',
    ]
    loop.close()



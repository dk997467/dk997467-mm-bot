import os
import json


def test_alerts_log_append_and_clear(tmp_path):
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._alerts_log_path = str(tmp_path / 'alerts.log')
    # minimal config/metrics
    srv.config = SimpleNamespace(rollout=SimpleNamespace(traffic_split_pct=50, salt='s', blue={}, green={}), rollout_ramp=SimpleNamespace(enabled=True))
    class M:
        def __init__(self):
            self._rollout_fills = {'blue': 300, 'green': 300}
            self._rollout_rejects = {'blue': 0, 'green': 20}
            self._rollout_latency_ewma = {'blue': 10.0, 'green': 120.0}
            class G:
                def __init__(self, v=0):
                    self._v = v
                def _value(self):
                    return self
                def get(self):
                    return 0.0
            self.rollout_split_observed_pct = SimpleNamespace(_value=SimpleNamespace(get=lambda: 50.0))
            self.rollout_ramp_step_idx = SimpleNamespace(_value=SimpleNamespace(get=lambda: 1))
            self.rollout_ramp_frozen = SimpleNamespace(_value=SimpleNamespace(get=lambda: 0))
            self.rollout_ramp_cooldown_seconds = SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0))
            self._ramp_holds_counts = {}
            self._alerts = []
        def inc_admin_alert_event(self, kind):
            self._alerts.append(kind)
        def set_rollout_split_pct(self, v):
            pass
    srv.metrics = M()
    # enable killswitch to force alert
    srv.config.killswitch = SimpleNamespace(enabled=True, dry_run=True, max_reject_delta=0.01, max_latency_delta_ms=10, min_fills=10, action='rollback')
    payload = srv._build_canary_payload()
    assert payload['killswitch']['fired'] is True
    # file should have lines
    with open(srv._alerts_log_path, 'r', encoding='utf-8') as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) >= 1
    rec = json.loads(lines[-1])
    assert 'kind' in rec and 'payload' in rec
    # clear via admin endpoint
    async def _call_clear():
        class Req:
            headers = {"X-Admin-Token": "t"}
            rel_url = type("U", (), {"query": {}})()
            pass
        req = Req()
        srv._check_admin_token = lambda r: True
        srv._admin_rate_limit_check = lambda a, e: True
        return await srv._admin_alerts_clear(req)
    import asyncio
    res = asyncio.run(_call_clear())
    assert res.status == 200
    with open(srv._alerts_log_path, 'r', encoding='utf-8') as f:
        content = f.read()
    assert content == ""


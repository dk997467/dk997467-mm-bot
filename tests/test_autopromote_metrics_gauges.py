import asyncio


def test_autopromote_metrics_gauges():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._ramp_state = {"frozen": False, "consecutive_stable_steps": 0}
    srv._ramp_step_idx = 1
    srv._rollout_state_dirty = False
    srv.config = SimpleNamespace(
        rollout=SimpleNamespace(traffic_split_pct=50, active='blue', salt='s', blue={}, green={}),
        rollout_ramp=SimpleNamespace(enabled=True),
        autopromote=SimpleNamespace(enabled=True, stable_steps_required=2, min_split_pct=25),
    )
    class M:
        def __init__(self):
            self._rollout_fills = {'blue': 1000, 'green': 1000}
            self._rollout_rejects = {'blue': 1, 'green': 1}
            self._rollout_latency_ewma = {'blue': 10.0, 'green': 10.0}
            self._rollout_orders_count = {'blue': 10, 'green': 10}
            self._ramp_holds_counts = {}
            self.stable = []
            self.attempt = 0
            self.flip = 0
        def set_autopromote_stable_steps(self, v):
            self.stable.append(v)
        def inc_autopromote_attempt(self):
            self.attempt += 1
        def inc_autopromote_flip(self):
            self.flip += 1
        def set_ramp_enabled(self, v):
            pass
        def set_ramp_step_idx(self, v):
            pass
        def set_rollout_split_pct(self, v):
            pass
    srv.metrics = M()
    asyncio.run(srv._rollout_ramp_tick())
    asyncio.run(srv._rollout_ramp_tick())
    assert len(srv.metrics.stable) >= 2
    assert srv.metrics.attempt >= 1
    assert srv.metrics.flip >= 1


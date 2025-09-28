import asyncio


def test_killswitch_rollback_action():
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._ramp_step_idx = 2
    srv._ramp_state = {'frozen': False}
    srv._ramp_last_counters = {"fills": {"blue": 0, "green": 0}, "rejects": {"blue": 0, "green": 0}}
    srv.config = SimpleNamespace(rollout=SimpleNamespace(traffic_split_pct=50, active='blue', salt='s', pinned_cids_green=[]), rollout_ramp=SimpleNamespace(enabled=True, steps_pct=[0,25,50], cooldown_after_rollback_sec=10), killswitch=SimpleNamespace(enabled=True, dry_run=False, max_reject_delta=0.01, max_latency_delta_ms=10, min_fills=10, action='rollback'))
    class M:
        def __init__(self):
            self._snap = {
                'fills': {'blue': 20, 'green': 20},
                'rejects': {'blue': 0, 'green': 2},
                'latency_ewma': {'blue': 10.0, 'green': 80.0},
            }
            self.triggers = []
        def _get_rollout_snapshot_for_tests(self):
            return self._snap
        def set_ramp_enabled(self, v):
            pass
        def set_ramp_step_idx(self, v):
            pass
        def inc_ramp_hold(self, r):
            pass
        def set_ramp_frozen(self, v):
            pass
        def set_rollout_split_pct(self, v):
            pass
        def inc_killswitch_check(self):
            pass
        def inc_killswitch_trigger(self, action):
            self.triggers.append(action)
    srv.metrics = M()
    asyncio.run(srv._rollout_ramp_tick())
    # rollback applied: step decreased to 1 and cooldown set
    assert srv._ramp_step_idx == 1
    assert getattr(srv, '_ramp_cooldown_until', 0.0) > 0.0
    assert 'rollback' in srv.metrics.triggers



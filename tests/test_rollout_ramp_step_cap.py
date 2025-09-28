import asyncio
import time


def test_rollout_ramp_step_cap(monkeypatch):
    from cli.run_bot import MarketMakerBot
    srv = MarketMakerBot.__new__(MarketMakerBot)

    class RampCfg:
        enabled = True
        steps_pct = [0, 30, 80]
        step_interval_sec = 1
        max_reject_rate_delta_pct = 2.0
        max_latency_delta_ms = 50
        max_pnl_delta_usd = 0.0
        min_sample_fills = 1
        max_step_increase_pct = 10
        cooldown_after_rollback_sec = 0

    srv.config = type("Cfg", (), {
        "rollout": type("R", (), {"traffic_split_pct": 0})(),
        "rollout_ramp": RampCfg()
    })()

    class M:
        def _get_rollout_snapshot_for_tests(self):
            return {
                "fills": {"blue": 1000, "green": 1000},
                "rejects": {"blue": 0, "green": 0},
                "latency_ewma": {"blue": 10.0, "green": 10.0},
            }
        def set_rollout_split_pct(self, v): pass
        def set_ramp_step_idx(self, i): pass
        def inc_ramp_transition(self, direction): pass
        def inc_ramp_hold(self, reason): pass
        def set_ramp_cooldown_seconds(self, v): pass

    srv.metrics = M()
    srv._ramp_step_idx = 0
    srv._ramp_last_counters = {"fills": {"blue": 0, "green": 0}, "rejects": {"blue": 0, "green": 0}}
    srv._ramp_last_check_ts = int(time.time())
    srv._ramp_state = {}

    asyncio.run(srv._rollout_ramp_tick())

    assert 0 < srv.config.rollout.traffic_split_pct <= 10


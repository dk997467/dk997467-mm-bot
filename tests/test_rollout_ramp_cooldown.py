import asyncio
import time


def test_rollout_ramp_cooldown(monkeypatch):
    from cli.run_bot import MarketMakerBot
    srv = MarketMakerBot.__new__(MarketMakerBot)

    class RampCfg:
        enabled = True
        steps_pct = [0, 10, 20]
        step_interval_sec = 1
        max_reject_rate_delta_pct = 2.0
        max_latency_delta_ms = 50
        max_pnl_delta_usd = 0.0
        min_sample_fills = 1
        max_step_increase_pct = 50
        cooldown_after_rollback_sec = 300

    srv.config = type("Cfg", (), {
        "rollout": type("R", (), {"traffic_split_pct": 10})(),
        "rollout_ramp": RampCfg()
    })()

    now = int(time.time())
    srv._ramp_cooldown_until = now + 300
    srv._ramp_state = {}

    class M:
        def __init__(self): self.holds_cool=0; self.cooldown=0
        def _get_rollout_snapshot_for_tests(self):
            return {
                "fills": {"blue": 1000, "green": 1000},
                "rejects": {"blue": 0, "green": 0},
                "latency_ewma": {"blue": 10.0, "green": 10.0},
            }
        def inc_ramp_hold(self, reason):
            if reason == 'cooldown': self.holds_cool += 1
        def set_ramp_cooldown_seconds(self, v): self.cooldown = v
        def set_rollout_split_pct(self, v): pass
        def set_ramp_step_idx(self, i): pass
        def inc_ramp_transition(self, direction): pass

    srv.metrics = M()
    srv._ramp_step_idx = 1  # 10%
    srv._ramp_last_counters = {"fills": {"blue": 0, "green": 0}, "rejects": {"blue": 0, "green": 0}}
    srv._ramp_last_check_ts = now

    asyncio.run(srv._rollout_ramp_tick())

    assert srv.config.rollout.traffic_split_pct == 10
    assert srv.metrics.holds_cool >= 1
    assert srv.metrics.cooldown > 0


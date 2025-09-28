"""
Freeze on incident in ramp tick.
"""
import asyncio
from types import SimpleNamespace


def test_rollout_ramp_freeze_on_incident():
    from cli.run_bot import MarketMakerBot

    class _MetricsStub:
        def __init__(self):
            self._fills_b = 0
            self._fills_g = 0
            self._rej_b = 0
            self._rej_g = 0
            self._lat_b = 0.0
            self._lat_g = 0.0
        def _get_rollout_snapshot_for_tests(self):
            return {
                'fills': {'blue': self._fills_b, 'green': self._fills_g},
                'rejects': {'blue': self._rej_b, 'green': self._rej_g},
                'latency_ewma': {'blue': self._lat_b, 'green': self._lat_g},
                'split': 20,
            }
        def set_ramp_enabled(self, v): pass
        def set_ramp_step_idx(self, i): pass
        def set_rollout_split_pct(self, v): pass
        def inc_ramp_transition(self, d): pass
        def inc_ramp_rollback(self): pass
        def inc_ramp_freeze(self): pass
        def set_ramp_frozen(self, s): pass

    bot = MarketMakerBot(config_path="config.yaml", recorder=None, dry_run=True)
    from src.common.config import RolloutRampConfig
    bot.config = SimpleNamespace(rollout=SimpleNamespace(traffic_split_pct=20), rollout_ramp=RolloutRampConfig(enabled=True, steps_pct=[0,10,20], step_interval_sec=10))
    bot.metrics = _MetricsStub()
    bot._ramp_step_idx = 2
    # Incident: high rejects and latency green vs blue
    bot.metrics._fills_b = 10
    bot.metrics._fills_g = 10
    bot.metrics._rej_b = 0
    bot.metrics._rej_g = 6
    bot.metrics._lat_b = 50
    bot.metrics._lat_g = 250

    async def run_once():
        await bot._rollout_ramp_tick()
        # frozen and step down due to kill-switch
        assert bot._ramp_state['frozen'] is True
        assert bot.config.rollout.traffic_split_pct == 10
    asyncio.run(run_once())



import asyncio
from prometheus_client import REGISTRY
from types import SimpleNamespace

from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


def _reset_registry():
    try:
        for col in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass


def test_latency_slo_loop_respects_running(tmp_path):
    _reset_registry()
    from cli.run_bot import MarketMakerBot
    cfg = AppConfig()
    cfg.latency_slo.enabled = True
    cfg.latency_slo.window_sec = 1
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot.metrics = m
    bot.config = cfg
    bot._get_artifacts_dir = lambda: str(tmp_path)
    bot._alerts_log_path = str(tmp_path / 'alerts.log')
    # seed latencies
    for _ in range(10):
        m.inc_rollout_fill('blue', 10.0)
        m.inc_rollout_fill('green', 20.0)
    # when running=False, loop body should effectively do nothing across sleep slices
    bot.running = False
    async def run_short():
        task = asyncio.create_task(bot._latency_slo_loop())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except Exception:
            pass
    asyncio.get_event_loop().run_until_complete(run_short())
    # No alerts file created
    assert not (tmp_path / 'alerts.log').exists()



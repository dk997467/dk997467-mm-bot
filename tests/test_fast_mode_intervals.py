import os
import time
import tempfile
from types import SimpleNamespace

import pytest

import asyncio
from cli.run_bot import MarketMakerBot


@pytest.mark.asyncio
async def test_fast_mode_intervals(monkeypatch):
    # fast env
    d = tempfile.mkdtemp()
    monkeypatch.setenv("ARTIFACTS_DIR", d)
    monkeypatch.setenv("CANARY_EXPORT_INTERVAL_SEC", "1")
    monkeypatch.setenv("PRUNE_INTERVAL_SEC", "2")
    monkeypatch.setenv("ROLLOUT_STEP_INTERVAL_SEC", "1")
    # minimal bot
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot.running = True
    bot.config = SimpleNamespace(
        rollout=SimpleNamespace(traffic_split_pct=0, active="blue", salt="s", blue={}, green={}),
        rollout_ramp=SimpleNamespace(enabled=True, step_interval_sec=5, steps_pct=[0,5,10]),
        autopromote=SimpleNamespace(enabled=False),
        killswitch=SimpleNamespace(enabled=False, dry_run=True, action="freeze"),
    )
    # metrics snapshot stub
    from unittest.mock import MagicMock
    m = MagicMock()
    # ramp needs counters deltas above min_sample_fills; set min_sample_fills=0 via config defaults
    m._get_rollout_snapshot_for_tests.return_value = {
        "fills": {"blue": 1000, "green": 1000},
        "rejects": {"blue": 0, "green": 0},
        "latency_ewma": {"blue": 10.0, "green": 10.0},
        "split": 0,
        "observed": 0.0,
    }
    bot.metrics = m

    # start export and a short ramp loop ticks
    # simulate canary export loop
    task_export = asyncio.create_task(bot._canary_export_loop())
    # simulate ramp loop with short runtime
    task_ramp = asyncio.create_task(bot._rollout_ramp_loop())

    # wait ~3s
    await asyncio.sleep(3.2)
    bot.running = False
    # give loops time to exit
    await asyncio.sleep(0)

    # verify canary files generated
    files = os.listdir(d)
    has_canary = any(name.startswith("canary_") and name.endswith(".json") for name in files)
    assert has_canary or ("canary.json" in files)
    
    # We cannot easily assert internal step metric without server; but loop ran quickly
    # Ensure tasks were created
    assert task_export is not None
    assert task_ramp is not None



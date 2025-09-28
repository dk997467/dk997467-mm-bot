import os


def test_rollout_state_snapshot_atomic_write(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot.metrics = SimpleNamespace(inc_rollout_state_snapshot_write=lambda ok, ts: None)
    bot.config = SimpleNamespace(
        rollout=SimpleNamespace(traffic_split_pct=20, active='blue', salt='s', pinned_cids_green=[], blue={}, green={}),
        rollout_ramp=SimpleNamespace(enabled=False, steps_pct=[0,5,10], step_interval_sec=600, max_reject_rate_delta_pct=2.0, max_latency_delta_ms=50, max_pnl_delta_usd=0.0)
    )
    bot._rollout_state_snapshot_path = str(tmp_path / "state.json")
    bot._rollout_state_snapshot_interval = 1
    bot._rollout_state_jitter_frac = 0.10
    bot._rollout_state_dirty = True
    # ensure parent exists
    os.makedirs(tmp_path, exist_ok=True)

    # monkeypatch os.replace and fsync
    calls = {"fsync": 0, "replace": 0}
    def fake_fsync(fd):
        calls["fsync"] += 1
    def fake_replace(a, b):
        calls["replace"] += 1
        return None
    monkeypatch.setattr('os.fsync', fake_fsync)
    monkeypatch.setattr('os.replace', fake_replace)

    import asyncio
    async def run_once():
        # run one loop iteration then cancel
        task = asyncio.create_task(bot._rollout_state_snapshot_loop())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    asyncio.run(run_once())
    # fsync and replace should be called
    assert calls["fsync"] >= 1
    assert calls["replace"] >= 1


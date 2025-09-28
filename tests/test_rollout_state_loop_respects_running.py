import asyncio


def test_rollout_state_loop_respects_running():
    from cli.run_bot import MarketMakerBot
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv.running = True
    srv._rollout_state_snapshot_interval = 1
    srv._rollout_state_jitter_frac = 0.0
    srv._rollout_state_dirty = False
    srv._rollout_state_snapshot_path = "artifacts/rollout_state.json"

    async def go():
        t = asyncio.create_task(srv._rollout_state_snapshot_loop())
        await asyncio.sleep(0.05)
        srv.running = False
        await asyncio.sleep(0)
        await asyncio.wait_for(t, timeout=0.5)
        # after completion there should be no lingering task ref if set
        if hasattr(srv, '_rollout_state_task'):
            srv._rollout_state_task = None

    asyncio.run(go())


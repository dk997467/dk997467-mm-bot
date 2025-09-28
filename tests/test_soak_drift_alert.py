import os
import json
import asyncio


def test_soak_drift_alert(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    from tests.e2e._utils import make_metrics_ctx
    # set strict envs
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setenv('SOAK_WINDOW_SEC', '1')
    monkeypatch.setenv('SOAK_DRIFT_MAX_MS', '1')
    # build server instance skeleton
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    srv.metrics = make_metrics_ctx()
    srv.running = True

    # monkeypatch sleep to create artificial drift
    import time
    real_sleep = asyncio.sleep

    async def slow_sleep(v):
        # emulate heavy drift by actually sleeping longer
        await real_sleep(min(0.001, float(v)))
        # busy-wait to inflate perf_counter delta
        t0 = time.perf_counter()
        while (time.perf_counter() - t0) * 1000.0 < 10.0:
            pass

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(asyncio.wait_for(srv._soak_guard_loop().__anext__() if False else asyncio.sleep(0), timeout=0.01))
    except Exception:
        pass
    try:
        monkeypatch.setattr(asyncio, 'sleep', slow_sleep)
        task = loop.create_task(srv._soak_guard_loop())
        # let it tick a few times
        loop.run_until_complete(asyncio.sleep(0.2))
        srv.running = False
        loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        try:
            task.cancel()
        except Exception:
            pass
        loop.close()
        # restore
        monkeypatch.setattr(asyncio, 'sleep', real_sleep)

    # check alerts.log contains soak_guard_breach
    ap = tmp_path / 'alerts.log'
    assert ap.exists()
    lines = ap.read_text(encoding='utf-8').splitlines()
    assert any(json.loads(ln).get('kind') == 'soak_guard_breach' for ln in lines)



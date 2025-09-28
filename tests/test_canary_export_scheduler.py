import os
import time
import glob
import asyncio


def test_canary_export_scheduler(tmp_path, monkeypatch):
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    # set short interval
    monkeypatch.setenv('CANARY_EXPORT_INTERVAL_SEC', '1')
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv.config = SimpleNamespace(monitoring=SimpleNamespace(health_port=0))
    srv._build_time_iso = '1970-01-01T00:00:00Z'
    srv._params_hash = 'ph'
    srv.metrics = SimpleNamespace(
        rollout_split_observed_pct=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        _rollout_orders_count={'blue': 0, 'green': 0},
        _rollout_fills={'blue': 0, 'green': 0},
        _rollout_rejects={'blue': 0, 'green': 0},
        _rollout_latency_ewma={'blue': 0.0, 'green': 0.0},
        rollout_ramp_step_idx=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        rollout_ramp_frozen=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        _ramp_holds_counts={'sample': 0, 'cooldown': 0},
        rollout_ramp_cooldown_seconds=SimpleNamespace(_value=SimpleNamespace(get=lambda: 0.0)),
        inc_admin_request=lambda ep: None,
        inc_admin_rate_limited=lambda ep: None,
        inc_admin_unauthorized=lambda ep: None,
    )
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    srv._canary_export_interval = 1
    srv.running = True
    # chdir to tmp artifacts
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        loop = asyncio.new_event_loop()
        task = loop.create_task(srv._canary_export_loop())
        loop.run_until_complete(asyncio.sleep(2.2))
        srv.running = False
        loop.run_until_complete(asyncio.sleep(0))
        try:
            task.cancel()
        except Exception:
            pass
        files_json = glob.glob('artifacts/canary_*.json')
        files_md = glob.glob('artifacts/REPORT_CANARY_*.md')
        assert files_json and files_md
        loop.close()
    finally:
        os.chdir(cwd)



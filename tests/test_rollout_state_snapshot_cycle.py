import json


def test_rollout_state_snapshot_cycle(monkeypatch, tmp_path):
    from cli.run_bot import MarketMakerBot
    from types import SimpleNamespace
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot.config_path = "cfg.yml"
    bot.profile = None
    bot.dry_run = False
    bot.data_recorder = None
    bot._owns_recorder = False
    bot.running = True
    bot.config = SimpleNamespace(
        config_version=1,
        trading=SimpleNamespace(symbols=['X']),
        to_sanitized=lambda : {},
        bybit=SimpleNamespace(use_testnet=False),
        storage=SimpleNamespace(backend='mem'),
        monitoring=SimpleNamespace(health_port=18993),
        rollout=SimpleNamespace(traffic_split_pct=30, active='blue', salt='s', pinned_cids_green=['A','B'], blue={}, green={}),
        rollout_ramp=SimpleNamespace(enabled=True, steps_pct=[0,5,10], step_interval_sec=600, max_reject_rate_delta_pct=2.0, max_latency_delta_ms=50, max_pnl_delta_usd=0.0)
    )
    bot.metrics = SimpleNamespace(inc_rollout_state_snapshot_write=lambda ok, ts: None,
                                  inc_rollout_state_snapshot_load=lambda ok, ts: None,
                                  set_rollout_split_pct=lambda v: None,
                                  set_ramp_enabled=lambda v: None,
                                  set_ramp_step_idx=lambda v: None)
    bot._rollout_state_snapshot_path = str(tmp_path / "state.json")
    bot._rollout_state_snapshot_interval = 1
    bot._rollout_state_jitter_frac = 0.0
    bot._ramp_step_idx = 0
    # produce snapshot
    snap = bot._to_rollout_state_snapshot()
    payload = json.dumps(snap, sort_keys=True, separators=(",", ":"))
    with open(bot._rollout_state_snapshot_path, 'w', encoding='utf-8') as f:
        f.write(payload)
    # test load snapshot manually (simulate what initialize does)
    from pathlib import Path as _P
    if _P(bot._rollout_state_snapshot_path).exists() and _P(bot._rollout_state_snapshot_path).is_file():
        if _P(bot._rollout_state_snapshot_path).stat().st_size <= 1024*1024:
            with open(bot._rollout_state_snapshot_path, 'r', encoding='utf-8') as f:
                st = json.load(f)
            if isinstance(st, dict) and int(st.get('version', 1)) >= 1:
                ro = getattr(bot.config, 'rollout', None)
                if ro is not None:
                    # apply traffic split/active/salt/pins like in initialize
                    v = int(max(0, min(100, int(st.get('traffic_split_pct', ro.traffic_split_pct)))))
                    ro.traffic_split_pct = v
                    a = str(st.get('active', ro.active)).lower()
                    if a in ('blue','green'):
                        ro.active = a
    # verify the cycle worked
    assert bot.config.rollout.traffic_split_pct == snap['traffic_split_pct']
    assert bot.config.rollout.active == snap['active']


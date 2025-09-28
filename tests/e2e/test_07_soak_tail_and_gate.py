import os
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds, CANARY_GATE_PER_SYMBOL
from tests.e2e._utils import make_metrics_ctx, seed_latency_tail


async def _call_get(handler, path_query: dict | None = None):
    class Req:
        headers = {"X-Admin-Token": "t"}
        rel_url = type("U", (), {"query": (path_query or {})})()
        method = 'GET'
    return await handler(Req())


def test_soak_tail_and_gate(tmp_path, monkeypatch):
    # Fast-mode ENV
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    monkeypatch.setenv('ROLLOUT_STEP_INTERVAL_SEC', '1')
    monkeypatch.setenv('CANARY_EXPORT_INTERVAL_SEC', '1')
    monkeypatch.setenv('PRUNE_INTERVAL_SEC', '2')
    monkeypatch.setenv('LAT_MIN_SAMPLE', '200')
    monkeypatch.setenv('LAT_P95_CAP_MS', '50')
    monkeypatch.setenv('LAT_P99_CAP_MS', '100')
    monkeypatch.setenv('ALERTS_MAX_LINES', '5')
    monkeypatch.setenv('CANARY_MAX_SNAPSHOTS', '3')

    # Prepare metrics with heavy GREEN tail
    m = make_metrics_ctx()
    blue = [5.0, 10.0, 15.0, 20.0] * 100  # 400 samples <=20ms
    green = [5.0, 10.0, 15.0] * 100 + [400.0, 800.0, 1600.0] * 150  # 450 heavy tail samples
    seed_latency_tail(m, blue_profile=blue, green_profile=green)

    # Build server and canary payload
    from cli.run_bot import MarketMakerBot
    srv = MarketMakerBot.__new__(MarketMakerBot)
    srv._ensure_admin_audit_initialized()
    srv._check_admin_token = lambda req: True
    srv._admin_rate_limit_check = lambda actor, ep: True
    srv.metrics = m
    # Minimal config with rollout
    srv.config = SimpleNamespace(
        rollout=SimpleNamespace(traffic_split_pct=50, active='blue', salt='salt', blue={}, green={}),
        rollout_ramp=SimpleNamespace(enabled=True),
        killswitch=SimpleNamespace(enabled=False, dry_run=True, max_reject_delta=0.02, max_latency_delta_ms=50),
        autopromote=SimpleNamespace(enabled=False, stable_steps_required=6, min_split_pct=25),
    )

    # Generate canary JSON once via admin generate
    loop = asyncio.new_event_loop()
    try:
        # /admin/report/canary
        res = loop.run_until_complete(_call_get(srv._admin_report_canary))
        assert res.status == 200
        payload = json.loads(res.text)
        hints = payload.get('hints', [])
        # Triage tail hints present
        assert 'latency_tail_regression_p95' in hints
        assert 'latency_tail_regression_p99' in hints
        # Deltas exceed caps deterministically
        p95_d = float(payload['rollout']['latency_ms_p95_delta'])
        p99_d = float(payload['rollout']['latency_ms_p99_delta'])
        assert p95_d > 50.0
        assert p99_d > 100.0

        # Gate evaluate with per-symbol override (ensure thresholds used)
        CANARY_GATE_PER_SYMBOL.clear()
        CANARY_GATE_PER_SYMBOL['BTCUSDT'] = {
            'tail_min_sample': 200,
            'tail_p95_cap_ms': 50,
            'tail_p99_cap_ms': 100,
        }
        canary = {
            'killswitch_fired': False,
            'drift_alert': False,
            'fills_blue': 1000,
            'fills_green': 1000,
            'rejects_blue': 0,
            'rejects_green': 0,
            'latency_ms_avg_blue': 10.0,
            'latency_ms_avg_green': 20.0,
            'latency_ms_p95_blue': float(payload['rollout']['latency_ms_p95_blue']),
            'latency_ms_p95_green': float(payload['rollout']['latency_ms_p95_green']),
            'latency_ms_p99_blue': float(payload['rollout']['latency_ms_p99_blue']),
            'latency_ms_p99_green': float(payload['rollout']['latency_ms_p99_green']),
            'latency_samples_blue': int(payload['rollout']['latency_samples_blue']),
            'latency_samples_green': int(payload['rollout']['latency_samples_green']),
        }
        ok, reasons, metrics = evaluate(wf_report={"symbol": "BTCUSDT", "canary": canary}, thresholds=GateThresholds())
        cg = metrics.get('canary_gate_reasons', [])
        # Order must be: ... latency_tail_p95_exceeds -> latency_tail_p99_exceeds
        assert 'latency_tail_p95_exceeds' in cg
        assert 'latency_tail_p99_exceeds' in cg
        assert cg.index('latency_tail_p95_exceeds') < cg.index('latency_tail_p99_exceeds')

        # Alerts log written and prune keeps tail
        # Generate export to write artifacts
        res2 = loop.run_until_complete(srv._admin_report_canary_generate(type('R', (), {'headers': {'X-Admin-Token': 't'}, 'method': 'POST'})()))
        assert res2.status == 200
        # Read alerts log via admin: should have triage_hints entry
        resp_alerts = loop.run_until_complete(_call_get(srv._admin_alerts_log, {"tail": "10"}))
        assert resp_alerts.status == 200
        data = json.loads(resp_alerts.text)
        assert any(it.get('kind') == 'triage_hints' for it in data.get('items', []))

        # Write multiple alert lines to exceed tail cap
        for _ in range(10):
            _ = loop.run_until_complete(_call_get(srv._admin_report_canary))

        # Create synthetic canary_* files to exercise prune count
        art = Path(os.environ['ARTIFACTS_DIR'])
        art.mkdir(parents=True, exist_ok=True)
        created = []
        for i in range(6):
            jp = art / f'canary_20240101_000{i:02d}.json'
            mp = art / f'REPORT_CANARY_20240101_000{i:02d}.md'
            jp.write_text('{}', encoding='utf-8')
            mp.write_text('x', encoding='utf-8')
            ts = time.time() - (10 - i) * 86400
            os.utime(jp, (ts, ts))
            os.utime(mp, (ts, ts))
            created.append(jp)
            created.append(mp)

        # Run prune loop briefly
        srv.running = True
        srv._prune_interval = 0.2
        async def run_prune_once():
            t = asyncio.create_task(srv._prune_artifacts_loop())
            await asyncio.sleep(0.35)
            srv.running = False
            await asyncio.sleep(0)
            try:
                await asyncio.wait_for(t, timeout=1.0)
            except Exception:
                pass
        loop.run_until_complete(run_prune_once())

        # Check prune effects
        remaining_json = sorted(art.glob('canary_*.json'))
        remaining_md = sorted(art.glob('REPORT_CANARY_*.md'))
        assert len(remaining_json) <= 3
        assert len(remaining_md) <= 3
        with open(art / 'alerts.log', 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        assert len(lines) <= 5
    finally:
        try:
            loop.close()
        except Exception:
            pass



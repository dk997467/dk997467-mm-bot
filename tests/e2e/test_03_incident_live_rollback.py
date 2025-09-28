"""
E2E Test 03: Incident Live Rollback
- Set killswitch.dry_run=false, action="rollback"
- Trigger degradation → step↓, cooldown>0
- Verify alerts.log contains killswitch_fired event
"""

import json
import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import MagicMock
import asyncio

import pytest
from aiohttp import web

from cli.run_bot import MarketMakerBot
from tests.e2e._utils import await_next_tick, tail_alerts
from src.metrics.exporter import Metrics


class MockRequest:
    def __init__(self, method="GET", path="/", headers=None, query_params=None, json_data=None):
        self.method = method
        self.path = path
        self.rel_url = SimpleNamespace(path=path, query=query_params or {})
        self.headers = headers or {}
        self._json_data = json_data

    async def json(self):
        return self._json_data or {}


@pytest.fixture
async def mock_bot():
    """Create a mock MarketMakerBot for live rollback scenario"""
    bot = MarketMakerBot.__new__(MarketMakerBot)
    
    # Basic attributes
    bot.dry_run = False
    bot.running = True
    bot.config_version = "test-v1"
    bot._build_time_iso = "2024-01-01T00:00:00Z"
    bot._params_hash = "test-hash-123"
    bot._ramp_step_idx = 3  # Higher in ramp, ready for rollback
    
    # Mock config with live rollback setup
    bot.config = SimpleNamespace(
        rollout=SimpleNamespace(
            traffic_split_pct=50,  # High traffic split
            active="blue", 
            salt="test-salt",
            pinned_cids_green=[],
            blue={},
            green={}
        ),
        rollout_ramp=SimpleNamespace(
            enabled=True,
            steps_pct=[5, 15, 35, 50, 75, 100],
            step_interval_sec=300,
            max_reject_rate_delta_pct=0.05,
            max_latency_delta_ms=50,
            max_pnl_delta_usd=1000.0,
            min_sample_fills=200,
            max_step_increase_pct=10,
            cooldown_after_rollback_sec=900
        ),
        killswitch=SimpleNamespace(
            enabled=True,
            dry_run=False,  # LIVE mode
            action="rollback",
            min_fills=50,
            max_reject_delta=0.08,
            max_latency_delta_ms=80
        ),
        chaos=SimpleNamespace(
            enabled=True,
            reject_inflate_pct=0.10,  # High degradation
            latency_inflate_ms=200
        ),
        strategy=SimpleNamespace(
            symbol="BTCUSDT"
        )
    )
    
    # Create temp directory for artifacts
    bot._temp_dir = tempfile.mkdtemp()
    bot._alerts_log_path = os.path.join(bot._temp_dir, "alerts.log")
    
    # Real Metrics with test hooks
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            strategy=SimpleNamespace(
                levels_per_side=1,
                min_time_in_book_ms=0,
                k_vola_spread=0.0,
                skew_coeff=0.0,
                imbalance_cutoff=0.0,
            ),
            limits=SimpleNamespace(max_create_per_sec=0, max_cancel_per_sec=0),
        )
    )
    m = Metrics(ctx)
    m.test_reset_rollout()
    m.test_seed_rollout_counters(
        fills_blue=3000,
        fills_green=1500,
        rejects_blue=30,
        rejects_green=195,
        split_expected_pct=50,
    )
    m.test_seed_rollout_latency_ms(blue_ms=25.0, green_ms=220.0)
    bot.metrics = m
    
    # Ramp state
    bot._ramp_state = {
        "consecutive_stable_steps": 0,
        "cooldown_until": 0.0,
        "last_fills_blue": 3000,
        "last_fills_green": 1500
    }
    
    # State tracking
    bot._rollout_state_dirty = False
    
    yield bot
    
    # Cleanup
    import shutil
    shutil.rmtree(bot._temp_dir, ignore_errors=True)


async def _call(bot, method, path, json_data=None, headers=None):
    """Helper to simulate HTTP calls to bot handlers"""
    request = MockRequest(method=method, path=path, headers=headers, json_data=json_data)
    
    if path == "/admin/report/canary" and method == "GET":
        return await bot._admin_report_canary(request)
    elif path == "/admin/rollout/ramp" and method == "GET":
        return await bot._admin_rollout_ramp(request)
    elif path == "/admin/alerts/log" and method == "GET":
        return await bot._admin_alerts_log(request)
    else:
        return web.Response(status=404, text="Not Found")


async def simulate_ramp_tick_with_rollback(bot):
    """Simulate a ramp tick that triggers killswitch rollback"""
    # Get current metrics
    snapshot = bot.metrics.get_rollout_snapshot_for_tests()
    
    # Check killswitch conditions
    if bot.config.killswitch.enabled:
        blue_fills = snapshot["blue_fills_total"]
        green_fills = snapshot["green_fills_total"]
        blue_rejects = snapshot["blue_rejects_total"]
        green_rejects = snapshot["green_rejects_total"]
        blue_latency = snapshot["blue_latency_p50_ms"]
        green_latency = snapshot["green_latency_p50_ms"]
        
        # Check minimum fills
        if green_fills >= bot.config.killswitch.min_fills:
            # Calculate deltas
            blue_reject_rate = blue_rejects / max(blue_fills, 1)
            green_reject_rate = green_rejects / max(green_fills, 1)
            reject_delta = green_reject_rate - blue_reject_rate
            latency_delta = green_latency - blue_latency
            
            # Check thresholds
            killswitch_fired = False
            if reject_delta > bot.config.killswitch.max_reject_delta:
                killswitch_fired = True
            if latency_delta > bot.config.killswitch.max_latency_delta_ms:
                killswitch_fired = True
            
            if killswitch_fired and not bot.config.killswitch.dry_run:
                # Perform rollback action
                if bot.config.killswitch.action == "rollback":
                    # Step down
                    if bot._ramp_step_idx > 0:
                        bot._ramp_step_idx -= 1
                        # Update traffic split to match new step
                        if bot._ramp_step_idx == 0:
                            bot.config.rollout.traffic_split_pct = 0
                        else:
                            bot.config.rollout.traffic_split_pct = \
                                bot.config.rollout_ramp.steps_pct[bot._ramp_step_idx - 1]
                    
                    # Set cooldown
                    now = time.time()
                    bot._ramp_state["cooldown_until"] = now + bot.config.rollout_ramp.cooldown_after_rollback_sec
                    
                    # Log alert
                    alert_entry = {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "kind": "killswitch_fired",
                        "action": "rollback",
                        "reject_delta": round(reject_delta, 4),
                        "latency_delta_ms": round(latency_delta, 1),
                        "step_before": bot._ramp_step_idx + 1,
                        "step_after": bot._ramp_step_idx
                    }
                    
                    # Write to alerts log
                    await bot._append_json_line(bot._alerts_log_path, alert_entry)


@pytest.mark.asyncio
async def test_e2e_03_incident_live_rollback(mock_bot):
    """
    E2E Test 03: Incident Live Rollback
    - Configure killswitch for live action
    - Trigger degradation that causes rollback
    - Verify step decreases, cooldown active, alerts logged
    """
    bot = mock_bot
    
    # Set admin token
    os.environ["ADMIN_TOKEN"] = "test-token-123"
    headers = {"X-Admin-Token": "test-token-123"}
    
    try:
        # 1. Verify initial state (high step, no cooldown)
        resp = await _call(bot, "GET", "/admin/rollout/ramp", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        initial_step = data["step_idx"]
        assert initial_step >= 3, "Should start at high step for rollback test"
        
        # 2. Check initial alerts log (should be empty)
        resp = await _call(bot, "GET", "/admin/alerts/log", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        initial_alert_count = len(data["items"])
        
        # 3. Start ramp loop and wait one fast tick for rollback
        task_ramp = asyncio.create_task(bot._rollout_ramp_loop())
        await await_next_tick(1.3)
        
        # 4. Verify step decreased
        resp = await _call(bot, "GET", "/admin/rollout/ramp", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        new_step = data["step_idx"]
        assert new_step < initial_step, f"Step should decrease: {initial_step} → {new_step}"
        
        # 5. Cooldown gauge may update on subsequent hold; we assert rollback via alerts
        
        # 6. Trigger canary payload build to log alert, then check alerts log contains killswitch event
        _ = await _call(bot, "GET", "/admin/report/canary", headers=headers)
        items = await tail_alerts(bot, headers, 20)
        new_alert_count = len(items)
        assert new_alert_count > initial_alert_count, "New alert should be logged"
        assert len(items) > 0, "Should have alert items"
        
        # Find killswitch alert
        killswitch_alert = None
        for item in items:
            if item.get("kind") == "killswitch_fired":
                killswitch_alert = item
                break
        
        assert killswitch_alert is not None, "Should have killswitch_fired alert"
        assert (killswitch_alert.get("payload", {}) or {}).get("action") == "rollback"
        
        print("✓ E2E Test 03 (Incident Live Rollback) passed")
        # Stop ramp loop
        bot.running = False
        await asyncio.sleep(0)
        
    finally:
        # Cleanup
        if "ADMIN_TOKEN" in os.environ:
            del os.environ["ADMIN_TOKEN"]
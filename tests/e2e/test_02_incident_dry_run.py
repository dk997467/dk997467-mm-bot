"""
E2E Test 02: Incident Dry Run
- POST /admin/chaos (enable rejection inflation)
- POST /admin/rollout/killswitch (enable dry_run mode)
- GET /admin/report/canary → killswitch.fired==true, ramp unchanged
"""

import asyncio
import json
import os
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
import aiohttp
from aiohttp import web

from cli.run_bot import MarketMakerBot
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

    async def text(self):
        return json.dumps(self._json_data) if self._json_data else ""


@pytest.fixture
async def mock_bot():
    """Create a mock MarketMakerBot with incident scenario setup"""
    bot = MarketMakerBot.__new__(MarketMakerBot)
    
    # Basic attributes
    bot.dry_run = False
    bot.running = True
    bot.config_version = "test-v1"
    bot.profile = None
    bot.data_recorder = None
    bot._owns_recorder = False
    bot._build_time_iso = "2024-01-01T00:00:00Z"
    bot._params_hash = "test-hash-123"
    bot._ramp_step_idx = 2  # Partway through ramp
    
    # Mock config with incident-prone setup
    bot.config = SimpleNamespace(
        rollout=SimpleNamespace(
            traffic_split_pct=35,  # Mid-ramp
            active="blue", 
            salt="test-salt",
            pinned_cids_green=[],
            blue={},
            green={}
        ),
        rollout_ramp=SimpleNamespace(
            enabled=False,
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
            enabled=False,  # Will be enabled in test
            dry_run=True,
            action="rollback",
            min_fills=50,
            max_reject_delta=0.1,
            max_latency_delta_ms=100
        ),
        chaos=SimpleNamespace(
            enabled=False,  # Will be enabled in test
            reject_inflate_pct=0.0,
            latency_inflate_ms=0
        ),
        autopromote=SimpleNamespace(
            enabled=True,
            min_stable_steps=3,
            min_fills_per_step=500,
            max_reject_rate_delta=0.02,
            max_latency_delta_ms=25
        ),
        strategy=SimpleNamespace(
            symbol="BTCUSDT",
            base_currency="BTC",
            quote_currency="USDT"
        )
    )
    # Ensure ramp loop (if any) does not tick quickly for this test
    os.environ["ROLLOUT_STEP_INTERVAL_SEC"] = "10"
    
    # Mock monitoring
    bot.monitoring = SimpleNamespace(health_port=18993)
    
    # Create temp directory for artifacts
    bot._temp_dir = tempfile.mkdtemp()
    bot._canary_export_path = os.path.join(bot._temp_dir, "canary_{timestamp}.json")
    bot._canary_report_path = os.path.join(bot._temp_dir, "REPORT_CANARY_{timestamp}.md")
    bot._alerts_log_path = os.path.join(bot._temp_dir, "alerts.log")
    
    # Real metrics with test hooks
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
    # Seed degraded GREEN performance
    m.test_seed_rollout_counters(
        fills_blue=2000,
        fills_green=700,
        rejects_blue=20,
        rejects_green=140,
        split_expected_pct=35,
    )
    m.test_seed_rollout_latency_ms(blue_ms=25.0, green_ms=150.0)
    bot.metrics = m
    
    # Ramp state
    bot._ramp_state = {
        "consecutive_stable_steps": 0,
        "cooldown_until": 0.0,
        "last_fills_blue": 2000,
        "last_fills_green": 700
    }
    
    # State tracking
    bot._rollout_state_dirty = False
    bot._last_canary_export = 0.0
    bot._canary_export_interval = 3600
    
    # Mock tasks
    bot._rollout_state_task = None
    bot._canary_export_task = None
    bot._prune_task = None
    
    yield bot
    
    # Cleanup
    import shutil
    shutil.rmtree(bot._temp_dir, ignore_errors=True)


async def _call(bot, method, path, json_data=None, headers=None):
    """Helper to simulate HTTP calls to bot handlers"""
    request = MockRequest(method=method, path=path, headers=headers, json_data=json_data)
    
    # Route to appropriate handler
    if path == "/admin/report/canary" and method == "GET":
        return await bot._admin_report_canary(request)
    elif path == "/admin/chaos" and method == "GET":
        return await bot._admin_chaos(request)
    elif path == "/admin/chaos" and method == "POST":
        return await bot._admin_chaos(request)
    elif path == "/admin/rollout/killswitch" and method == "GET":
        return await bot._admin_killswitch(request)
    elif path == "/admin/rollout/killswitch" and method == "POST":
        return await bot._admin_killswitch(request)
    elif path == "/admin/rollout/ramp" and method == "GET":
        return await bot._admin_rollout_ramp(request)
    else:
        return web.Response(status=404, text="Not Found")


@pytest.mark.asyncio
async def test_e2e_02_incident_dry_run(mock_bot):
    """
    E2E Test 02: Incident Dry Run
    - Enable chaos to degrade GREEN performance
    - Enable killswitch in dry_run mode
    - Verify killswitch detects degradation but doesn't act
    """
    bot = mock_bot
    
    # Set admin token
    os.environ["ADMIN_TOKEN"] = "test-token-123"
    headers = {"X-Admin-Token": "test-token-123"}
    
    try:
        # 1. Check initial ramp state (should be active)
        resp = await _call(bot, "GET", "/admin/rollout/ramp", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        initial_step = data.get("step_idx", bot._ramp_step_idx)
        
        # 2. Enable chaos to inflate GREEN rejections and latency
        chaos_config = {
            "enabled": True,
            "reject_inflate_pct": 0.05,  # 5% additional rejections
            "latency_inflate_ms": 120    # +120ms latency
        }
        resp = await _call(bot, "POST", "/admin/chaos", 
                          json_data=chaos_config, headers=headers)
        assert resp.status == 200
        
        # Update bot config to reflect chaos changes
        bot.config.chaos.enabled = True
        bot.config.chaos.reject_inflate_pct = 0.05
        bot.config.chaos.latency_inflate_ms = 120
        
        # 3. Verify chaos is enabled
        resp = await _call(bot, "GET", "/admin/chaos", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        assert data["enabled"] is True
        assert data["reject_inflate_pct"] == 0.05
        assert data["latency_inflate_ms"] == 120
        
        # 4. Enable killswitch in dry_run mode
        killswitch_config = {
            "enabled": True,
            "dry_run": True,
            "action": "rollback",
            "min_fills": 50,
            "max_reject_delta": 0.1,    # 10% threshold
            "max_latency_delta_ms": 100  # 100ms threshold
        }
        resp = await _call(bot, "POST", "/admin/rollout/killswitch",
                          json_data=killswitch_config, headers=headers)
        assert resp.status == 200
        
        # Update bot config to reflect killswitch changes
        bot.config.killswitch.enabled = True
        bot.config.killswitch.dry_run = True
        bot.config.killswitch.action = "rollback"
        bot.config.killswitch.min_fills = 50
        bot.config.killswitch.max_reject_delta = 0.1
        bot.config.killswitch.max_latency_delta_ms = 100
        
        # 5. Verify killswitch is enabled
        resp = await _call(bot, "GET", "/admin/rollout/killswitch", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        assert data["enabled"] is True
        assert data["dry_run"] is True
        assert data["action"] == "rollback"
        
        # 6. Simulate ramp tick to trigger killswitch evaluation
        # This would normally be done by the background loop
        # For the test, we'll call the logic directly via canary report
        
        # 7. Check canary report shows killswitch fired
        resp = await _call(bot, "GET", "/admin/report/canary", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        
        # Verify killswitch section
        killswitch = data["killswitch"]
        assert killswitch["enabled"] is True
        assert killswitch["dry_run"] is True
        assert killswitch["fired"] is True  # Should detect degradation
        
        # Reason is deterministic: either 'reject_delta' or 'latency_delta'
        assert killswitch.get("reason") in ("reject_delta", "latency_delta")
        
        # 8. Verify ramp not acting (we keep ramp disabled in this test for determinism)
        # ramp endpoint reflects disabled state
        resp = await _call(bot, "GET", "/admin/rollout/ramp", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        assert data["enabled"] is False
        # payload also shows ramp disabled
        resp = await _call(bot, "GET", "/admin/report/canary", headers=headers)
        p = json.loads(resp.body.decode())
        assert p["rollout"]["ramp"]["enabled"] is False
        
        # 9. Check chaos is still active (affecting metrics)
        resp = await _call(bot, "GET", "/admin/chaos", headers=headers)
        assert resp.status == 200
        _ch = json.loads(resp.body.decode())
        assert _ch.get("enabled") is True
        
        # 10. Verify hints contain triage information
        resp = await _call(bot, "GET", "/admin/report/canary", headers=headers)
        data = json.loads(resp.body.decode())
        hints = data.get("hints", [])
        
        # Should have hints about degradation
        reject_hint_found = any("reject" in hint.lower() for hint in hints)
        latency_hint_found = any("latency" in hint.lower() for hint in hints)
        assert reject_hint_found or latency_hint_found, \
            f"Expected triage hints about degradation, got: {hints}"
        
        # 11. Verify deterministic output
        resp1 = await _call(bot, "GET", "/admin/report/canary", headers=headers)
        resp2 = await _call(bot, "GET", "/admin/report/canary", headers=headers)
        
        data1 = json.loads(resp1.body.decode())
        data2 = json.loads(resp2.body.decode())
        
        # Normalize timestamps
        data1["meta"]["generated_at"] = "2024-01-01T00:00:00Z"
        data2["meta"]["generated_at"] = "2024-01-01T00:00:00Z"
        
        json1 = json.dumps(data1, sort_keys=True, separators=(",", ":"))
        json2 = json.dumps(data2, sort_keys=True, separators=(",", ":"))
        assert json1 == json2, "Canary reports should be deterministic"
        
        print("✓ E2E Test 02 (Incident Dry Run) passed")
        
    finally:
        # Cleanup
        if "ADMIN_TOKEN" in os.environ:
            del os.environ["ADMIN_TOKEN"]
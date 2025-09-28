"""
E2E Test 01: Happy Path
- Start mock context/web
- Check /healthz, /readyz
- Verify empty alerts
- Verify first canary export appears
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
from src.common.config import Config
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
    """Create a mock MarketMakerBot with minimal setup for e2e testing"""
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
    bot._ramp_step_idx = 0
    
    # Mock config with all required sections
    bot.config = SimpleNamespace(
        rollout=SimpleNamespace(
            traffic_split_pct=0,
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
            enabled=False,
            dry_run=True,
            action="freeze",
            min_fills=100,
            max_reject_delta=0.1,
            max_latency_delta_ms=100
        ),
        chaos=SimpleNamespace(
            enabled=False,
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
    
    # Mock monitoring
    bot.monitoring = SimpleNamespace(health_port=18993)
    
    # Create temp directory for artifacts
    bot._temp_dir = tempfile.mkdtemp()
    bot._canary_export_path = os.path.join(bot._temp_dir, "canary_{timestamp}.json")
    bot._canary_report_path = os.path.join(bot._temp_dir, "REPORT_CANARY_{timestamp}.md")
    bot._alerts_log_path = os.path.join(bot._temp_dir, "alerts.log")
    
    # Mock metrics
    bot.metrics = MagicMock()
    bot.metrics.get_rollout_snapshot_for_tests.return_value = {
        "blue_fills_total": 1000,
        "green_fills_total": 50,
        "blue_rejects_total": 10,
        "green_rejects_total": 2,
        "blue_latency_p50_ms": 25.0,
        "green_latency_p50_ms": 30.0,
        "blue_pnl_usd": 500.0,
        "green_pnl_usd": 25.0
    }
    
    # Mock rollout ramp step_idx to be 0
    mock_step_idx = MagicMock()
    mock_step_idx._value.get.return_value = 0
    bot.metrics.rollout_ramp_step_idx = mock_step_idx
    
    # Mock other metrics to prevent hints
    bot.metrics._ramp_holds_counts = {"sample": 0, "cooldown": 0}
    mock_cooldown = MagicMock()
    mock_cooldown._value.get.return_value = 0.0
    bot.metrics.rollout_ramp_cooldown_seconds = mock_cooldown
    
    # Ramp state
    bot._ramp_state = {
        "consecutive_stable_steps": 0,
        "cooldown_until": 0.0,
        "last_fills_blue": 1000,
        "last_fills_green": 50
    }
    
    # State tracking
    bot._rollout_state_dirty = False
    bot._last_canary_export = 0.0
    bot._canary_export_interval = 3600  # 1 hour
    
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
    if path == "/healthz":
        return await bot._sre_healthz(request)
    elif path == "/readyz":
        return await bot._sre_readyz(request)
    elif path == "/admin/report/canary" and method == "GET":
        return await bot._admin_report_canary(request)
    elif path == "/admin/report/canary/generate" and method == "POST":
        return await bot._admin_report_canary_generate(request)
    elif path == "/admin/alerts/log" and method == "GET":
        return await bot._admin_alerts_log(request)
    elif path == "/admin/chaos" and method == "GET":
        return await bot._admin_chaos(request)
    elif path == "/admin/chaos" and method == "POST":
        return await bot._admin_chaos(request)
    elif path == "/admin/rollout/killswitch" and method == "GET":
        return await bot._admin_killswitch(request)
    elif path == "/admin/rollout/killswitch" and method == "POST":
        return await bot._admin_killswitch(request)
    else:
        return web.Response(status=404, text="Not Found")


@pytest.mark.asyncio
async def test_e2e_01_happy_path(mock_bot):
    """
    E2E Test 01: Happy Path
    - Check basic health endpoints
    - Verify empty alerts log
    - Generate first canary export
    """
    bot = mock_bot
    
    # Set admin token for authenticated requests
    os.environ["ADMIN_TOKEN"] = "test-token-123"
    headers = {"X-Admin-Token": "test-token-123"}
    
    try:
        # Ensure clean alerts log path - override if it's pointing to global path
        if not bot._alerts_log_path.startswith(bot._temp_dir):
            bot._alerts_log_path = os.path.join(bot._temp_dir, "alerts.log")
        
        # Clear any existing alerts log for clean test
        if os.path.exists(bot._alerts_log_path):
            os.remove(bot._alerts_log_path)
        
        # Also clear global alerts.log if it exists
        global_alerts_path = "artifacts/alerts.log"
        if os.path.exists(global_alerts_path):
            os.remove(global_alerts_path)
        
        # 1. Check health endpoints
        resp = await _call(bot, "GET", "/healthz")
        assert resp.status == 200
        
        resp = await _call(bot, "GET", "/readyz")
        assert resp.status == 200
        
        # 2. Check empty alerts log initially
        resp = await _call(bot, "GET", "/admin/alerts/log", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        assert data["items"] == []
        
        # 3. Check initial chaos state
        resp = await _call(bot, "GET", "/admin/chaos", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        assert data["enabled"] is False
        assert data["reject_inflate_pct"] == 0.0
        assert data["latency_inflate_ms"] == 0
        
        # 4. Check initial killswitch state
        resp = await _call(bot, "GET", "/admin/rollout/killswitch", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        assert data["enabled"] is False
        assert data["dry_run"] is True
        
        # 5. Generate first canary report
        resp = await _call(bot, "POST", "/admin/report/canary/generate", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        assert data["status"] == "ok"
        
        # 6. Verify canary report structure
        resp = await _call(bot, "GET", "/admin/report/canary", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        
        # Check required top-level fields
        required_fields = [
            "meta", "rollout", "drift", "hints", "killswitch", "autopromote"
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Check meta section
        assert "commit" in data["meta"]
        assert "params_hash" in data["meta"]
        assert "generated_at" in data["meta"]
        
        # Check rollout section
        assert data["rollout"]["split_expected_pct"] == 0
        assert data["rollout"]["salt_hash"] != ""  # Should have salt hash
        
        # Check ramp section
        ramp = data["rollout"]["ramp"]
        assert ramp["enabled"] is False
        assert ramp["step_idx"] == 0
        
        # Check drift section
        assert data["drift"]["alert"] is False
        assert data["drift"]["reason"] == "ok"
        
        # Check killswitch section
        assert data["killswitch"]["enabled"] is False
        assert data["killswitch"]["fired"] is False
        
        # Check hints (should be empty for healthy state)
        assert data["hints"] == []
        
        # Check autopromote section
        assert data["autopromote"]["enabled"] is True
        assert data["autopromote"]["stable_steps_current"] == 0
        
        # 7. Verify deterministic JSON (byte-identical on repeat)
        resp1 = await _call(bot, "GET", "/admin/report/canary", headers=headers)
        resp2 = await _call(bot, "GET", "/admin/report/canary", headers=headers)
        
        # Parse and re-encode to ensure same timestamp doesn't cause issues
        data1 = json.loads(resp1.body.decode())
        data2 = json.loads(resp2.body.decode())
        
        # Set same generated_at for comparison (build time is deterministic in test)
        data1["meta"]["generated_at"] = "2024-01-01T00:00:00Z"
        data2["meta"]["generated_at"] = "2024-01-01T00:00:00Z"
        
        json1 = json.dumps(data1, sort_keys=True, separators=(",", ":"))
        json2 = json.dumps(data2, sort_keys=True, separators=(",", ":"))
        assert json1 == json2, "JSON responses should be deterministic"
        
        print("✓ E2E Test 01 (Happy Path) passed")
        
    finally:
        # Cleanup
        if "ADMIN_TOKEN" in os.environ:
            del os.environ["ADMIN_TOKEN"]
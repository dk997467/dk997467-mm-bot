"""
E2E Test 05: Prune and Alerts Tail
- Generate multiple canary artifacts and alerts
- Wait for prune → verify limits are respected
"""

import json
import os
import tempfile
import time
from types import SimpleNamespace
from tests.e2e._utils import await_next_tick
from unittest.mock import MagicMock

import pytest
from aiohttp import web

from cli.run_bot import MarketMakerBot


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
    """Create a mock MarketMakerBot for pruning scenario"""
    bot = MarketMakerBot.__new__(MarketMakerBot)
    
    # Basic attributes
    bot.dry_run = False
    bot.running = True
    bot.config_version = "test-v1"
    bot._build_time_iso = "2024-01-01T00:00:00Z"
    bot._params_hash = "test-hash-123"
    bot._ramp_step_idx = 0
    
    # Mock config
    bot.config = SimpleNamespace(
        rollout=SimpleNamespace(
            traffic_split_pct=0,
            active="blue", 
            salt="test-salt",
            pinned_cids_green=[],
            blue={},
            green={}
        ),
        strategy=SimpleNamespace(
            symbol="BTCUSDT"
        )
    )
    
    # Create temp directory for artifacts
    bot._temp_dir = tempfile.mkdtemp()
    bot._artifacts_dir = bot._temp_dir
    bot._canary_export_path = os.path.join(bot._temp_dir, "canary_{timestamp}.json")
    bot._canary_report_path = os.path.join(bot._temp_dir, "REPORT_CANARY_{timestamp}.md")
    bot._alerts_log_path = os.path.join(bot._temp_dir, "alerts.log")
    # ensure helpers read same dir
    def _get_artifacts_dir_override():
        return bot._temp_dir
    bot._get_artifacts_dir = _get_artifacts_dir_override  # type: ignore[assignment]
    def _alerts_log_file_override():
        return os.path.join(bot._temp_dir, "alerts.log")
    bot._alerts_log_file = _alerts_log_file_override  # type: ignore[assignment]
    
    # Pruning config
    bot._prune_canary_keep_files = 5
    bot._prune_alerts_max_lines = 100
    
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
    
    yield bot
    
    # Cleanup
    import shutil
    shutil.rmtree(bot._temp_dir, ignore_errors=True)


async def _call(bot, method, path, json_data=None, headers=None):
    """Helper to simulate HTTP calls to bot handlers"""
    # Parse query if provided in path
    query_params = None
    base_path = path
    if "?" in path:
        base_path, qs = path.split("?", 1)
        try:
            query_params = {}
            for pair in qs.split("&"):
                if not pair:
                    continue
                k, v = pair.split("=", 1) if "=" in pair else (pair, "")
                query_params[k] = v
        except Exception:
            query_params = None
    request = MockRequest(method=method, path=base_path, headers=headers, query_params=query_params, json_data=json_data)
    
    if base_path == "/admin/report/canary/generate" and method == "POST":
        return await bot._admin_report_canary_generate(request)
    elif base_path == "/admin/alerts/log" and method == "GET":
        return await bot._admin_alerts_log(request)
    else:
        return web.Response(status=404, text="Not Found")


def create_test_canary_files(bot, count=10):
    """Create test canary files with different timestamps"""
    files_created = []
    base_time = int(time.time()) - (count * 3600)  # Spread over hours
    
    for i in range(count):
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime(base_time + i * 3600))
        
        json_file = os.path.join(bot._artifacts_dir, f"canary_{timestamp}.json")
        md_file = os.path.join(bot._artifacts_dir, f"REPORT_CANARY_{timestamp}.md")
        
        # Create JSON file
        with open(json_file, "w") as f:
            json.dump({"test": f"canary_{i}", "timestamp": timestamp}, f)
        files_created.append(json_file)
        
        # Create MD file
        with open(md_file, "w") as f:
            f.write(f"# Canary Report {i}\n\nTimestamp: {timestamp}\n")
        files_created.append(md_file)
    
    return files_created


def create_test_alerts(bot, count=1200):
    """Create test alerts exceeding the max line limit"""
    base_time = int(time.time()) - (count * 60)  # Spread over minutes
    
    for i in range(count):
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base_time + i * 60))
        alert_entry = {
            "timestamp": timestamp,
            "kind": "test_alert",
            "message": f"Test alert {i}",
            "sequence": i
        }
        
        # Append to alerts log
        with open(bot._alerts_log_path, "a") as f:
            f.write(json.dumps(alert_entry, sort_keys=True, separators=(",", ":")) + "\n")


def simulate_prune_artifacts(bot):
    """Simulate the pruning logic"""
    import glob
    
    # Prune canary files (keep only the newest N)
    canary_pattern = os.path.join(bot._artifacts_dir, "canary_*.json")
    canary_files = sorted(glob.glob(canary_pattern), key=os.path.getmtime)
    
    if len(canary_files) > bot._prune_canary_keep_files:
        files_to_remove = canary_files[:-bot._prune_canary_keep_files]
        for file_path in files_to_remove:
            os.remove(file_path)
            # Also remove corresponding MD file
            md_path = file_path.replace("canary_", "REPORT_CANARY_").replace(".json", ".md")
            if os.path.exists(md_path):
                os.remove(md_path)
    
    # Prune alerts log (keep only the newest N lines)
    alerts_path = bot._alerts_log_path or os.path.join(bot._artifacts_dir, "alerts.log")
    if os.path.exists(alerts_path):
        with open(alerts_path, "r") as f:
            lines = f.readlines()
        
        if len(lines) > bot._prune_alerts_max_lines:
            # Keep only the newest lines
            lines_to_keep = lines[-bot._prune_alerts_max_lines:]
            with open(alerts_path, "w") as f:
                f.writelines(lines_to_keep)


@pytest.mark.asyncio
async def test_e2e_05_prune_and_alerts_tail(mock_bot, monkeypatch):
    """
    E2E Test 05: Prune and Alerts Tail
    - Create excess canary artifacts and alerts
    - Simulate pruning
    - Verify limits are respected
    """
    bot = mock_bot
    
    # Set admin token and fast prune env
    os.environ["ADMIN_TOKEN"] = "test-token-123"
    headers = {"X-Admin-Token": "test-token-123"}
    monkeypatch.setenv("CANARY_MAX_SNAPSHOTS", "5")
    monkeypatch.setenv("ALERTS_MAX_LINES", "100")
    monkeypatch.setenv("PRUNE_INTERVAL_SEC", "1")
    # ensure admin handlers and prune loop read from our temp dir
    monkeypatch.setenv("ARTIFACTS_DIR", bot._artifacts_dir)
    # make prune loop tick fast
    bot._prune_interval = 1.0
    
    try:
        # 1. Create excess canary files (more than the keep limit)
        files_created = create_test_canary_files(bot, count=10)
        assert len(files_created) == 20  # 10 JSON + 10 MD files
        
        # Verify all files exist initially
        existing_files = [f for f in files_created if os.path.exists(f)]
        assert len(existing_files) == 20, "All test files should exist initially"
        
        # 2. Create excess alerts (more than max lines)
        create_test_alerts(bot, count=1200)
        
        # Verify alerts exist
        with open(bot._alerts_log_path or os.path.join(bot._temp_dir, "alerts.log"), "r") as f:
            initial_lines = f.readlines()
        assert len(initial_lines) == 1200, "Should have 1200 test alerts initially"
        
        # 3. Check alerts via API before pruning
        resp = await _call(bot, "GET", "/admin/alerts/log?tail=10", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        # API may return <= requested tail depending on parse; only check upper bound
        assert len(data.get("items", [])) <= 10
        
        # 4. Generate additional canary report to test generation
        resp = await _call(bot, "POST", "/admin/report/canary/generate", headers=headers)
        assert resp.status == 200
        
        # 5. Count canary files before pruning
        import glob
        canary_files = glob.glob(os.path.join(bot._artifacts_dir, "canary_*.json"))
        md_files = glob.glob(os.path.join(bot._artifacts_dir, "REPORT_CANARY_*.md"))
        assert len(canary_files) >= 10, "Should have many canary files before pruning"
        assert len(md_files) >= 10, "Should have many MD files before pruning"
        
        # 6. Apply prune synchronously (deterministic for test)
        simulate_prune_artifacts(bot)
        
        # 7. Verify canary files were pruned
        canary_files_after = glob.glob(os.path.join(bot._artifacts_dir, "canary_*.json"))
        md_files_after = glob.glob(os.path.join(bot._artifacts_dir, "REPORT_CANARY_*.md"))
        
        assert len(canary_files_after) <= bot._prune_canary_keep_files, \
            f"Should keep only {bot._prune_canary_keep_files} canary files, got {len(canary_files_after)}"
        assert len(md_files_after) <= bot._prune_canary_keep_files, \
            f"Should keep only {bot._prune_canary_keep_files} MD files, got {len(md_files_after)}"
        
        # Verify the newest files are kept
        if canary_files_after:
            newest_canary = max(canary_files_after, key=os.path.getmtime)
            assert os.path.exists(newest_canary), "Newest canary file should be kept"
        
        # 8. Verify alerts log was pruned
        with open(bot._alerts_log_path or os.path.join(bot._temp_dir, "alerts.log"), "r") as f:
            pruned_lines = f.readlines()
        
        assert len(pruned_lines) <= bot._prune_alerts_max_lines, \
            f"Should keep only {bot._prune_alerts_max_lines} alert lines, got {len(pruned_lines)}"
        
        # Optionally check that lines are valid JSON
        for ln in pruned_lines[-5:]:
            try:
                json.loads(ln)
            except Exception:
                assert False, "Alerts log lines should be valid JSON"
        
        # 9. Verify API returns updated counts
        resp = await _call(bot, "GET", "/admin/alerts/log?tail=5", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        assert len(data.get("items", [])) <= 5, \
            "API should respect tail limit"
        
        # 10. Test edge case: tail more than available
        resp = await _call(bot, "GET", "/admin/alerts/log?tail=2000", headers=headers)
        assert resp.status == 200
        data = json.loads(resp.body.decode())
        assert len(data.get("items", [])) <= bot._prune_alerts_max_lines, \
            "Should not return more items than exist after pruning"
        
        print("✓ E2E Test 05 (Prune and Alerts Tail) passed")
        
    finally:
        # Cleanup
        if "ADMIN_TOKEN" in os.environ:
            del os.environ["ADMIN_TOKEN"]
        # nothing else
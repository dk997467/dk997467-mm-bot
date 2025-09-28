import os
import json
import tempfile
from types import SimpleNamespace

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


async def _call(bot, method, path, json_data=None, headers=None):
    request = MockRequest(method=method, path=path, headers=headers, json_data=json_data)
    if path == "/admin/alerts/log" and method == "GET":
        return await bot._admin_alerts_log(request)
    if path == "/admin/alerts/clear" and method == "POST":
        return await bot._admin_alerts_clear(request)
    if path == "/admin/report/canary/generate" and method == "POST":
        return await bot._admin_report_canary_generate(request)
    return web.Response(status=404, text="Not Found")


@pytest.mark.asyncio
async def test_artifacts_dir_isolation(monkeypatch):
    # two isolated dirs
    dir1 = tempfile.mkdtemp()
    dir2 = tempfile.mkdtemp()
    try:
        # First run in dir1
        monkeypatch.setenv("ARTIFACTS_DIR", dir1)
        bot1 = MarketMakerBot.__new__(MarketMakerBot)
        bot1.running = True
        # minimal config/metrics for canary generation
        bot1.config = SimpleNamespace(
            rollout=SimpleNamespace(traffic_split_pct=0, active="blue", salt="s", blue={}, green={}),
            rollout_ramp=SimpleNamespace(enabled=False),
            autopromote=SimpleNamespace(enabled=True, stable_steps_required=3, min_split_pct=25),
            killswitch=SimpleNamespace(enabled=False, dry_run=True, action="freeze"),
        )
        from unittest.mock import MagicMock
        m1 = MagicMock()
        m1._get_rollout_snapshot_for_tests.return_value = {"fills":{},"rejects":{},"latency_ewma":{},"split":0,"observed":0.0}
        bot1.metrics = m1
        os.environ["ADMIN_TOKEN"] = "t"
        headers = {"X-Admin-Token": "t"}
        # Clear alerts and generate one canary
        r = await _call(bot1, "POST", "/admin/alerts/clear", headers=headers)
        assert r.status == 200
        r = await _call(bot1, "POST", "/admin/report/canary/generate", headers=headers)
        if r.status != 200:
            try:
                print("canary_generate_error:", r.body.decode())
            except Exception:
                pass
        assert r.status == 200
        # Ensure files exist in dir1 only
        files1 = set(os.listdir(dir1))
        assert any(name.startswith("canary_") and name.endswith(".json") for name in files1) or "canary.json" in files1

        # Second run in dir2
        monkeypatch.setenv("ARTIFACTS_DIR", dir2)
        bot2 = MarketMakerBot.__new__(MarketMakerBot)
        bot2.running = True
        bot2.config = bot1.config
        bot2.metrics = m1
        r = await _call(bot2, "POST", "/admin/alerts/clear", headers=headers)
        assert r.status == 200
        # dir2 should be empty except possibly alerts.log
        files2 = set(os.listdir(dir2))
        # alerts.log may or may not exist; ensure no canary from dir1 leaked
        assert not any(name.startswith("canary_") or name == "canary.json" for name in files2)

        # GET alerts log in dir2 should be empty
        r = await _call(bot2, "GET", "/admin/alerts/log", headers=headers)
        assert r.status == 200
        data = json.loads(r.body.decode())
        assert data["items"] == []
    finally:
        # cleanup env var
        if "ARTIFACTS_DIR" in os.environ:
            del os.environ["ARTIFACTS_DIR"]


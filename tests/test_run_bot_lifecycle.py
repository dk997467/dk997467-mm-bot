import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import aiohttp
import pytest


class DummyREST:
    def __init__(self, *args, **kwargs):
        pass
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyWS:
    def __init__(self, *args, **kwargs):
        self._connected = True

    async def start(self):
        return None

    async def stop(self):
        return None

    def is_connected(self) -> bool:
        return True

    def get_connection_status(self) -> Dict[str, bool]:
        return {"public": True, "private": True, "overall": True}


class DummyMetrics:
    def __init__(self, *args, **kwargs):
        pass

    async def start(self):
        return None

    def stop(self):
        return None

    def get_metrics_endpoint(self) -> str:
        return "/metrics"

    # no-op update helpers
    def update_system_metrics(self, **kwargs):
        pass

    def update_websocket_status(self, **kwargs):
        pass

    def update_risk_metrics(self, **kwargs):
        pass

    def update_order_metrics(self, *args, **kwargs):
        pass

    def record_websocket_latency(self, *args, **kwargs):
        pass

    def record_order_latency(self, *args, **kwargs):
        pass

    def increment_market_data_updates(self, *args, **kwargs):
        pass

    def update_strategy_metrics(self, *args, **kwargs):
        pass

    def update_position_metrics(self, *args, **kwargs):
        pass
    
    def update_connection_status(self, *args, **kwargs):
        pass


class DummyOB:
    def get_mid_price(self):
        return 50000.0

    def get_microprice(self):
        return 50000.0

    def get_imbalance(self):
        return 0.0

    def get_spread_bps(self):
        return 2.0

    def get_total_depth(self, side: str, levels: int):
        return 1.0


class DummyAggregator:
    def __init__(self, *args, **kwargs):
        self.orderbooks: Dict[str, DummyOB] = {}

    def add_symbol(self, symbol: str):
        self.orderbooks[symbol] = DummyOB()

    def is_all_synced(self) -> bool:
        return True

    def update_orderbook(self, symbol: str, ob: Any):
        return None

    def update_delta(self, symbol: str, delta: Dict[str, Any]) -> bool:
        return True


@pytest.mark.asyncio
async def test_healthz_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Clear Prometheus registry to avoid duplicate metrics
    from prometheus_client import REGISTRY
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    # Prepare minimal config
    cfg = {
        "bybit": {"api_key": "k", "api_secret": "s", "use_testnet": True},
        "trading": {"symbols": ["BTCUSDT"]},
        "storage": {"backend": "parquet", "parquet_path": str(tmp_path / "data")},
        "monitoring": {"metrics_port": 18000, "health_port": 8001},
    }
    (tmp_path / "config.yaml").write_text(json.dumps(cfg))
    monkeypatch.chdir(tmp_path)

    import cli.run_bot as run_bot

    # Patch heavy dependencies with dummies
    monkeypatch.setattr(run_bot, "BybitRESTConnector", DummyREST)
    monkeypatch.setattr(run_bot, "BybitWebSocketConnector", DummyWS)
    monkeypatch.setattr(run_bot, "MetricsExporter", DummyMetrics)
    monkeypatch.setattr(run_bot, "OrderBookAggregator", DummyAggregator)

    # Make bot start/stop quick
    async def fast_start(self):
        await self._start_web_server()
        # Keep running for a short time to allow health check
        await asyncio.sleep(0.5)
        return None

    monkeypatch.setattr(run_bot.MarketMakerBot, "start", fast_start, raising=True)

    # Run main in background
    task = asyncio.create_task(run_bot.main())

    # Poll health endpoint
    ok = False
    for _ in range(30):  # up to ~3s
        await asyncio.sleep(0.1)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:8001/healthz") as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        ok = True
                        break
        except Exception:
            continue

    # Ensure the task finishes cleanly
    await task
    assert ok, "health endpoint did not return 200"


@pytest.mark.asyncio
async def test_recorder_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Clear Prometheus registry to avoid duplicate metrics
    from prometheus_client import REGISTRY
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    
    events: List[str] = []

    # Fake Recorder that records start/stop ordering
    class FakeRecorder:
        def __init__(self, *args, **kwargs):
            pass

        async def start(self):
            events.append("rec_start")

        async def stop(self):
            events.append("rec_stop")

        # minimal API used by run_bot
        async def record_custom_event(self, *args, **kwargs):
            return None

    # Patch heavy components
    import cli.run_bot as run_bot

    monkeypatch.setattr(run_bot, "BybitRESTConnector", DummyREST)
    monkeypatch.setattr(run_bot, "BybitWebSocketConnector", DummyWS)
    monkeypatch.setattr(run_bot, "MetricsExporter", DummyMetrics)
    monkeypatch.setattr(run_bot, "OrderBookAggregator", DummyAggregator)
    monkeypatch.setattr(run_bot, "Recorder", FakeRecorder)

    # Patch bot start/stop to be quick and record ordering
    async def fast_start(self):
        events.append("bot_start")
        # Start only the web server to match behavior
        await self._start_web_server()
        # Do not loop
        return None

    async def fast_stop(self):
        events.append("bot_stop")
        # Clean shutdown path
        if self.web_runner:
            await self.web_runner.cleanup()
        return None

    monkeypatch.setattr(run_bot.MarketMakerBot, "start", fast_start, raising=True)
    monkeypatch.setattr(run_bot.MarketMakerBot, "stop", fast_stop, raising=True)

    # Minimal config
    cfg = {
        "bybit": {"api_key": "k", "api_secret": "s", "use_testnet": True},
        "trading": {"symbols": ["BTCUSDT"]},
        "storage": {"backend": "parquet", "parquet_path": str(tmp_path / "data")},
        "monitoring": {"metrics_port": 18000, "health_port": 8001},
    }
    (tmp_path / "config.yaml").write_text(json.dumps(cfg))
    monkeypatch.chdir(tmp_path)

    await run_bot.main()

    # Check ordering: rec_start before bot_start; bot_stop before rec_stop
    assert events.index("rec_start") < events.index("bot_start")
    assert events.index("bot_stop") < events.index("rec_stop")



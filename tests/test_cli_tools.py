import asyncio
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest


@pytest.mark.asyncio
async def test_run_bot_config_parsing(tmp_path, monkeypatch):
    # Create minimal config.yaml with new structure
    cfg_content = {
        "strategy": {
            "enable_dynamic_spread": True,
            "enable_inventory_skew": True,
            "enable_adverse_guard": True,
        },
        "risk": {
            "enable_kill_switch": True,
        },
        "limits": {
            "max_active_per_side": 3,
        },
        "monitoring": {
            "enable_prometheus": True,
            "metrics_port": 18000,
            "health_port": 18001,
        },
        "storage": {
            "backend": "parquet",
            "parquet_path": str(tmp_path / "data")
        },
        "trading": {
            "symbols": ["BTCUSDT"]
        },
        "bybit": {
            "api_key": "k",
            "api_secret": "s",
            "use_testnet": True,
        }
    }
    (tmp_path / "config.yaml").write_text(json.dumps(cfg_content))
    monkeypatch.chdir(tmp_path)

    # Import after chdir so module sees our config
    import cli.run_bot as run_bot

    # Fake Recorder to assert start/stop calls
    created = []
    class FakeRecorder:
        def __init__(self, cfg):
            self.cfg = cfg
            self.started = False
            self.stopped = False
            created.append(self)

        async def start(self):
            self.started = True

        async def stop(self):
            self.stopped = True

    # Patch Recorder and MarketMakerBot methods to no-op
    monkeypatch.setattr(run_bot, "Recorder", FakeRecorder)

    async def _noop(self):
        return None

    monkeypatch.setattr(run_bot.MarketMakerBot, "initialize", _noop, raising=True)
    monkeypatch.setattr(run_bot.MarketMakerBot, "start", _noop, raising=True)
    monkeypatch.setattr(run_bot.MarketMakerBot, "stop", _noop, raising=True)

    # Avoid signal handler registration in tests environment
    import signal as _signal

    def _sig_noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(run_bot.signal, "signal", lambda *args, **kwargs: None)

    await run_bot.main()

    # Assert our FakeRecorder was created and started/stopped
    assert created, "Recorder was not instantiated"
    assert created[0].started is True
    assert created[0].stopped is True


@pytest.mark.asyncio
async def test_replay_events(tmp_path):
    # Build a tiny dataset
    data_dir = tmp_path / "data"
    (data_dir / "orders").mkdir(parents=True)
    (data_dir / "fills").mkdir(parents=True)
    (data_dir / "book_snapshots").mkdir(parents=True)

    t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 1, 1, 12, 0, 1, tzinfo=timezone.utc)
    t2 = datetime(2024, 1, 1, 12, 0, 2, tzinfo=timezone.utc)

    # Orders: one New and one Filled
    orders_df = pd.DataFrame(
        [
            {"timestamp": t0, "symbol": "BTCUSDT", "status": "New", "qty": 0.01},
            {"timestamp": t2, "symbol": "BTCUSDT", "status": "Filled", "qty": 0.01},
        ]
    )
    orders_df.to_parquet(data_dir / "orders" / "sample.parquet", index=False)

    # Fills: one execution matching the order
    fills_df = pd.DataFrame(
        [
            {
                "timestamp": t1,
                "order_id": "ord1",
                "trade_id": "tr1",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "qty": 0.01,
                "price": 50000.0,
                "fee": 0.05,
                "fee_rate": 0.0005,
                "exec_time": t1,
                "is_maker": True,
            }
        ]
    )
    fills_df.to_parquet(data_dir / "fills" / "sample.parquet", index=False)

    # Minimal snapshot rows (not heavily used in assertions here)
    snaps_df = pd.DataFrame(
        [
            {"timestamp": t0, "symbol": "BTCUSDT", "sequence": 1, "bids": "[]", "asks": "[]"}
        ]
    )
    snaps_df.to_parquet(data_dir / "book_snapshots" / "sample.parquet", index=False)

    # Minimal config-like object for ReplayEngine
    trading = SimpleNamespace(
        symbols=["BTCUSDT"],
        base_spread_bps=1.0,
        ladder_levels=1,
        ladder_step_bps=0.5,
        quote_refresh_ms=100,
        max_active_orders_per_side=10,
        price_band_tolerance_bps=2.0,
        max_retry_attempts=3,
        post_only=True,
        min_notional_usd=10,
    )
    risk = SimpleNamespace(
        max_position_usd=10000,
        target_inventory_usd=0,
        daily_max_loss_usd=1000,
        max_cancels_per_min=100,
        inventory_skew_gamma=0.1,
    )
    strategy = SimpleNamespace(
        volatility_lookback_sec=30, imbalance_weight=0.4, microprice_weight=0.6
    )
    config = SimpleNamespace(trading=trading, risk=risk, strategy=strategy)

    from cli.replay import ReplayEngine

    engine = ReplayEngine(config, ["BTCUSDT"])
    engine.load_events(data_dir, None, None, None)

    # Ensure events are sorted chronologically
    ts_list = [e["timestamp"] for e in engine.events]
    assert ts_list == sorted(ts_list)

    # Replay instantly (no sleep)
    await engine.replay_events(speed=0.0)

    # Assert basic stats
    m = engine.performance_metrics
    assert m["orders_placed"] == 1
    assert m["orders_filled"] == 1
    # Turnover equals qty*price from fills
    assert float(m["total_turnover"]) == pytest.approx(0.01 * 50000.0, rel=1e-6)



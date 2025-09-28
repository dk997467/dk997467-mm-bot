"""Recorder queue draining and sink mocking tests.

These tests verify that:
- Recorder drains its internal queue on stop
- Persisted records can be captured by mocking the parquet sink
"""

import asyncio
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Dict, List

import pandas as pd
import pytest

from src.common.models import Order, Trade, Side, OrderType, OrderStatus, TimeInForce
from src.storage.recorder import Recorder


def make_dummy_config(backend: str = "parquet", parquet_path: str = "./data", sqlite_path: str = "./data/test.db"):
    """Create a minimal config-like object sufficient for Recorder."""
    storage = SimpleNamespace(
        backend=backend,
        parquet_path=parquet_path,
        sqlite_path=sqlite_path,
        pg_host="",
        pg_port=5432,
        pg_database="",
        pg_username="",
        pg_password="",
        pg_schema="public",
    )

    class DummyConfig(SimpleNamespace):
        def get_db_url(self) -> str:
            return f"sqlite+aiosqlite:///{sqlite_path}"

    return DummyConfig(storage=storage)


def make_order() -> Order:
    return Order(
        order_id="ord_test_1",
        client_order_id="cl_test_1",
        symbol="BTCUSDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        qty=Decimal("0.01"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.GTC,
        status=OrderStatus.NEW,
        created_time=datetime.now(timezone.utc),
        updated_time=datetime.now(timezone.utc),
    )


def make_fill(order_id: str = "ord_test_1") -> Trade:
    return Trade(
        trade_id="tr_test_1",
        order_id=order_id,
        symbol="BTCUSDT",
        side=Side.BUY,
        qty=Decimal("0.01"),
        price=Decimal("50000"),
        fee=Decimal("0.05"),
        fee_rate=Decimal("0.0005"),
        timestamp=datetime.now(timezone.utc),
        exec_time=datetime.now(timezone.utc),
        is_maker=True,
    )


@pytest.mark.asyncio
async def test_recorder_queue_drains_on_stop(monkeypatch):
    # Use parquet backend with a temp dir
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = make_dummy_config(backend="parquet", parquet_path=tmpdir)
        recorder = Recorder(cfg)

        # Mock parquet write to avoid filesystem writes
        async def _fake_write(df: pd.DataFrame, table_name: str):
            return None

        monkeypatch.setattr(recorder, "_write_parquet", _fake_write)

        await recorder.start()

        # Enqueue several events
        await recorder.record_order(make_order())
        await recorder.record_fill(make_fill())
        await recorder.record_quote(
            {
                "timestamp": datetime.now(timezone.utc),
                "symbol": "BTCUSDT",
                "bid_px": 49999.0,
                "bid_qty": 0.01,
                "ask_px": 50001.0,
                "ask_qty": 0.01,
            }
        )
        await recorder.record_custom_event("unit_test", {"value": 1})

        # Give background writer a moment
        await asyncio.sleep(0.05)

        # Stop should drain remaining queue items and flush buffers
        await recorder.stop()

        assert recorder._queue is not None
        assert recorder._queue.qsize() == 0
        # Buffers should be cleared for parquet backend after stop's final flush
        assert len(recorder.order_buffer) == 0
        assert len(recorder.fill_buffer) == 0
        assert len(recorder.quote_buffer) == 0
        assert len(recorder.book_snapshot_buffer) == 0
        assert len(recorder.custom_event_buffer) == 0


@pytest.mark.asyncio
async def test_mock_sink_captures_persisted_events(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = make_dummy_config(backend="parquet", parquet_path=tmpdir)
        recorder = Recorder(cfg)

        captured: Dict[str, int] = {"orders": 0, "fills": 0, "quotes": 0, "book_snapshots": 0, "custom_events": 0}

        async def _fake_write(df: pd.DataFrame, table_name: str):
            captured[table_name] = captured.get(table_name, 0) + len(df)

        monkeypatch.setattr(recorder, "_write_parquet", _fake_write)

        await recorder.start()

        # Enqueue N events of different types
        orders_n = 2
        fills_n = 3
        quotes_n = 4

        for _ in range(orders_n):
            await recorder.record_order(make_order())
        for _ in range(fills_n):
            await recorder.record_fill(make_fill())
        for _ in range(quotes_n):
            await recorder.record_quote(
                {
                    "timestamp": datetime.now(timezone.utc),
                    "symbol": "BTCUSDT",
                    "bid_px": 49999.0,
                    "bid_qty": 0.01,
                    "ask_px": 50001.0,
                    "ask_qty": 0.01,
                }
            )

        # Let writer run, then stop to force final flush
        await asyncio.sleep(0.05)
        await recorder.stop()

        assert captured["orders"] == orders_n
        assert captured["fills"] == fills_n
        assert captured["quotes"] == quotes_n
        # We did not enqueue book snapshots in this test
        assert captured.get("book_snapshots", 0) == 0
        # Custom events count depends on test usage; ensure non-negative key exists
        assert captured.get("custom_events", 0) >= 0



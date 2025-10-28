"""Unit tests for FakeExchangeClient."""

from __future__ import annotations

import os

import pytest

from tools.live.exchange import (
    FakeExchangeClient,
    PlaceOrderRequest,
    Side,
    OrderStatus,
)


class TestFakeExchangeClient:
    """Test FakeExchangeClient deterministic behavior."""

    def test_place_order_success(self) -> None:
        """Test successful order placement."""
        client = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)

        req = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )

        resp = client.place_limit(req)

        assert resp.success is True
        assert resp.order_id is not None
        assert resp.order_id.startswith("ORD")
        assert resp.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.OPEN)

    def test_place_order_rejected(self) -> None:
        """Test order rejection."""
        client = FakeExchangeClient(fill_rate=1.0, reject_rate=1.0, seed=42)

        req = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )

        resp = client.place_limit(req)

        assert resp.success is False
        assert resp.order_id is None
        assert resp.status == OrderStatus.REJECTED
        assert resp.message is not None

    def test_deterministic_order_ids(self) -> None:
        """Test that order IDs are deterministic."""
        client1 = FakeExchangeClient(seed=42)
        client2 = FakeExchangeClient(seed=42)

        req = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )

        resp1 = client1.place_limit(req)
        resp2 = client2.place_limit(req)

        assert resp1.order_id == resp2.order_id

    def test_fill_rate_behavior(self) -> None:
        """Test fill rate controls fill probability."""
        # High fill rate
        client_high = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)
        fills_high = 0
        for i in range(10):
            req = PlaceOrderRequest(
                client_order_id=f"CLI{i:03d}",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.01,
                price=50000.0,
            )
            resp = client_high.place_limit(req)
            if resp.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                fills_high += 1

        # Low fill rate
        client_low = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)
        fills_low = 0
        for i in range(10):
            req = PlaceOrderRequest(
                client_order_id=f"CLI{i:03d}",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.01,
                price=50000.0,
            )
            resp = client_low.place_limit(req)
            if resp.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
                fills_low += 1

        assert fills_high > fills_low

    def test_cancel_order_success(self) -> None:
        """Test successful order cancellation."""
        client = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)

        req = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )

        resp = client.place_limit(req)
        assert resp.success is True

        success = client.cancel(resp.order_id)
        assert success is True

    def test_cancel_nonexistent_order(self) -> None:
        """Test canceling non-existent order."""
        client = FakeExchangeClient(seed=42)

        success = client.cancel("INVALID_ORDER_ID")
        assert success is False

    def test_cancel_filled_order(self) -> None:
        """Test canceling already filled order."""
        client = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)

        req = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )

        resp = client.place_limit(req)
        assert resp.success is True
        assert resp.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)

        # Cannot cancel filled order
        success = client.cancel(resp.order_id)
        assert success is False

    def test_get_open_orders(self) -> None:
        """Test getting open orders."""
        client = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)

        # Place 2 orders
        for i in range(2):
            req = PlaceOrderRequest(
                client_order_id=f"CLI{i:03d}",
                symbol="BTCUSDT",
                side=Side.BUY,
                qty=0.01,
                price=50000.0,
            )
            client.place_limit(req)

        open_orders = client.get_open_orders()
        assert len(open_orders) == 2

    def test_get_open_orders_filtered_by_symbol(self) -> None:
        """Test getting open orders filtered by symbol."""
        client = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)

        # Place orders for different symbols
        req1 = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )
        client.place_limit(req1)

        req2 = PlaceOrderRequest(
            client_order_id="CLI002",
            symbol="ETHUSDT",
            side=Side.BUY,
            qty=0.1,
            price=3000.0,
        )
        client.place_limit(req2)

        btc_orders = client.get_open_orders(symbol="BTCUSDT")
        assert len(btc_orders) == 1
        assert btc_orders[0].symbol == "BTCUSDT"

    def test_get_positions(self) -> None:
        """Test getting positions after fills."""
        client = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)

        # Place buy order
        req = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )
        client.place_limit(req)

        positions = client.get_positions()
        assert len(positions) >= 1

        btc_pos = next((p for p in positions if p.symbol == "BTCUSDT"), None)
        assert btc_pos is not None
        assert btc_pos.qty > 0  # Positive for long

    def test_stream_fills(self) -> None:
        """Test streaming fill events."""
        client = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)

        # Place order
        req = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )
        resp = client.place_limit(req)
        assert resp.success is True

        # Stream fills
        fills = list(client.stream_fills())
        assert len(fills) >= 1

        fill = fills[0]
        assert fill.order_id == resp.order_id
        assert fill.symbol == "BTCUSDT"
        assert fill.side == Side.BUY
        assert fill.qty > 0

    def test_reset(self) -> None:
        """Test reset clears all state."""
        client = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)

        # Place order
        req = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )
        client.place_limit(req)

        # Reset
        client.reset()

        # Verify state cleared
        assert len(client.get_open_orders()) == 0
        assert len(client.get_positions()) == 0
        assert len(list(client.stream_fills())) == 0

    def test_freeze_time_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test MM_FREEZE_UTC_ISO support."""
        monkeypatch.setenv("MM_FREEZE_UTC_ISO", "2025-01-01T00:00:00Z")

        client = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)

        req = PlaceOrderRequest(
            client_order_id="CLI001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.01,
            price=50000.0,
        )
        resp = client.place_limit(req)
        assert resp.success is True

        # Stream fills and check timestamp
        fills = list(client.stream_fills())
        assert len(fills) >= 1

        fill = fills[0]
        # Timestamp should be 2025-01-01 00:00:00 UTC
        expected_ts = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        assert fill.timestamp_ms == expected_ts


# Import for freeze time test
from datetime import datetime, timezone


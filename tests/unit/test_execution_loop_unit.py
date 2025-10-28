"""Unit tests for ExecutionLoop."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tools.live.exchange import FakeExchangeClient, Side
from tools.live.execution_loop import (
    ExecutionLoop,
    ExecutionParams,
    Quote,
    run_shadow_demo,
)
from tools.live.order_store import InMemoryOrderStore, OrderState
from tools.live.risk_monitor import RuntimeRiskMonitor


class TestExecutionLoop:
    """Test ExecutionLoop logic."""

    def test_initialization(self) -> None:
        """Test ExecutionLoop initialization."""
        exchange = FakeExchangeClient(seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        assert loop.exchange == exchange
        assert loop.order_store == store
        assert loop.risk_monitor == risk
        assert loop.stats["orders_placed"] == 0

    def test_on_quote_places_orders(self) -> None:
        """Test on_quote places buy and sell orders."""
        exchange = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        quote = Quote(symbol="BTCUSDT", bid=49990.0, ask=50010.0, timestamp_ms=1000)
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop.on_quote(quote, params)

        assert loop.stats["orders_placed"] == 2  # Buy and sell
        assert len(store.get_all()) == 2

    def test_on_quote_skips_when_frozen(self) -> None:
        """Test on_quote skips orders when system is frozen."""
        exchange = FakeExchangeClient(seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        # Freeze system
        risk.freeze("test_freeze")

        quote = Quote(symbol="BTCUSDT", bid=49990.0, ask=50010.0, timestamp_ms=1000)
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop.on_quote(quote, params)

        assert loop.stats["orders_placed"] == 0
        assert len(store.get_all()) == 0

    def test_on_quote_respects_risk_limits(self) -> None:
        """Test on_quote respects risk limits."""
        exchange = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10.0,  # Very low limit
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        quote = Quote(symbol="BTCUSDT", bid=49990.0, ask=50010.0, timestamp_ms=1000)
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
            base_qty=1.0,  # Large order
        )

        loop.on_quote(quote, params)

        # Orders should be blocked by risk
        assert loop.stats["risk_blocks"] > 0

    def test_on_fill_processes_fills(self) -> None:
        """Test on_fill processes fill events."""
        exchange = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        quote = Quote(symbol="BTCUSDT", bid=49990.0, ask=50010.0, timestamp_ms=1000)
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop.on_quote(quote, params)
        loop.on_fill()

        assert loop.stats["orders_filled"] > 0

    def test_on_edge_update_triggers_freeze(self) -> None:
        """Test on_edge_update triggers freeze when edge drops."""
        exchange = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=2.0,  # 2 bps threshold
        )

        loop = ExecutionLoop(exchange, store, risk)

        # Place some orders
        quote = Quote(symbol="BTCUSDT", bid=49990.0, ask=50010.0, timestamp_ms=1000)
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=2.0,
        )
        loop.on_quote(quote, params)

        # Trigger freeze with low edge
        loop.on_edge_update("BTCUSDT", 1.0)  # Below 2.0 threshold

        assert loop.stats["freeze_events"] == 1
        assert risk.is_frozen()

    def test_cancel_all_open_orders_on_freeze(self) -> None:
        """Test that all open orders are canceled on freeze."""
        exchange = FakeExchangeClient(fill_rate=0.0, reject_rate=0.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=2.0,
        )

        loop = ExecutionLoop(exchange, store, risk)

        # Place orders
        quote = Quote(symbol="BTCUSDT", bid=49990.0, ask=50010.0, timestamp_ms=1000)
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=2.0,
        )
        loop.on_quote(quote, params)

        open_before = len(store.get_open_orders())
        assert open_before > 0

        # Trigger freeze
        loop.on_edge_update("BTCUSDT", 1.0)

        # All orders should be canceled
        open_after = len(store.get_open_orders())
        assert open_after == 0
        assert loop.stats["orders_canceled"] > 0

    def test_run_shadow_generates_report(self) -> None:
        """Test run_shadow generates deterministic report."""
        exchange = FakeExchangeClient(fill_rate=0.5, reject_rate=0.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        params = ExecutionParams(
            symbols=["BTCUSDT", "ETHUSDT"],
            iterations=10,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        report = loop.run_shadow(params)

        assert "execution" in report
        assert "orders" in report
        assert "positions" in report
        assert "risk" in report
        assert "runtime" in report

        assert report["execution"]["iterations"] == 10
        assert set(report["execution"]["symbols"]) == {"BTCUSDT", "ETHUSDT"}

    def test_reset_clears_state(self) -> None:
        """Test reset clears all state."""
        exchange = FakeExchangeClient(seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        # Place some orders
        quote = Quote(symbol="BTCUSDT", bid=49990.0, ask=50010.0, timestamp_ms=1000)
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )
        loop.on_quote(quote, params)

        # Reset
        loop.reset()

        assert loop.stats["orders_placed"] == 0
        assert len(store.get_all()) == 0
        assert not risk.is_frozen()

    def test_rejected_orders_tracked(self) -> None:
        """Test rejected orders are tracked correctly."""
        exchange = FakeExchangeClient(fill_rate=0.0, reject_rate=1.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        quote = Quote(symbol="BTCUSDT", bid=49990.0, ask=50010.0, timestamp_ms=1000)
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=1,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop.on_quote(quote, params)

        assert loop.stats["orders_rejected"] > 0

        # Check store has rejected orders
        rejected_orders = store.get_by_state(OrderState.REJECTED)
        assert len(rejected_orders) > 0

    def test_custom_clock_injection(self) -> None:
        """Test custom clock can be injected."""
        exchange = FakeExchangeClient(seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        fixed_time = 1234567890000
        clock = lambda: fixed_time

        loop = ExecutionLoop(exchange, store, risk, clock=clock)

        assert loop._clock() == fixed_time

    def test_multiple_symbols(self) -> None:
        """Test execution with multiple symbols."""
        exchange = FakeExchangeClient(fill_rate=0.5, reject_rate=0.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        params = ExecutionParams(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            iterations=5,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        report = loop.run_shadow(params)

        assert len(report["execution"]["symbols"]) == 3
        assert "BTCUSDT" in report["execution"]["symbols"]
        assert "ETHUSDT" in report["execution"]["symbols"]
        assert "SOLUSDT" in report["execution"]["symbols"]

    def test_position_tracking(self) -> None:
        """Test position tracking after fills."""
        exchange = FakeExchangeClient(fill_rate=1.0, reject_rate=0.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=5,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        report = loop.run_shadow(params)

        positions = risk.get_positions()
        assert len(positions) > 0

    def test_deterministic_report_format(self) -> None:
        """Test report format is deterministic."""
        exchange = FakeExchangeClient(fill_rate=0.5, reject_rate=0.0, seed=42)
        store = InMemoryOrderStore()
        risk = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        loop = ExecutionLoop(exchange, store, risk)

        params = ExecutionParams(
            symbols=["BTCUSDT", "ETHUSDT"],
            iterations=5,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

        report = loop.run_shadow(params)

        # Symbols should be sorted
        assert report["execution"]["symbols"] == sorted(params.symbols)

        # positions.by_symbol should be sorted
        if report["positions"]["by_symbol"]:
            symbols = list(report["positions"]["by_symbol"].keys())
            assert symbols == sorted(symbols)


class TestRunShadowDemo:
    """Test run_shadow_demo function."""

    def test_run_shadow_demo_returns_json(self) -> None:
        """Test run_shadow_demo returns valid JSON."""
        result = run_shadow_demo(
            symbols=["BTCUSDT"],
            iterations=5,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
            fill_rate=0.5,
            reject_rate=0.05,
            latency_ms=10,
        )

        # Should be valid JSON
        report = json.loads(result)
        assert "execution" in report
        assert "orders" in report

        # Should end with newline
        assert result.endswith("\n")

    def test_run_shadow_demo_deterministic(self) -> None:
        """Test run_shadow_demo produces deterministic output."""
        result1 = run_shadow_demo(
            symbols=["BTCUSDT"],
            iterations=5,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
            fill_rate=0.5,
            reject_rate=0.05,
            latency_ms=10,
        )

        result2 = run_shadow_demo(
            symbols=["BTCUSDT"],
            iterations=5,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
            fill_rate=0.5,
            reject_rate=0.05,
            latency_ms=10,
        )

        # Except for runtime.utc, results should be identical
        report1 = json.loads(result1)
        report2 = json.loads(result2)

        del report1["runtime"]
        del report2["runtime"]

        assert report1 == report2

    def test_run_shadow_demo_with_freeze(self) -> None:
        """Test run_shadow_demo handles freezes correctly."""
        result = run_shadow_demo(
            symbols=["BTCUSDT"],
            iterations=50,  # Enough to trigger edge drop
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=5.0,  # Will be triggered
            fill_rate=0.5,
            reject_rate=0.0,
            latency_ms=1,
        )

        report = json.loads(result)
        
        # System should freeze due to edge drop
        assert report["risk"]["frozen"] is True
        assert report["risk"]["freeze_events"] > 0


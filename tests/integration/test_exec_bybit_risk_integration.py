"""
Integration tests for ExecutionLoop + BybitRestClient + RuntimeRiskMonitor.

Tests focus on:
- Freeze triggers cancel-all
- Risk limits block orders
- Deterministic JSON reports
"""

import json
import os
from unittest.mock import MagicMock

import pytest

from tools.live.exchange_bybit import BybitRestClient
from tools.live.execution_loop import ExecutionLoop, ExecutionParams, Quote
from tools.live.order_store import InMemoryOrderStore
from tools.live.risk_monitor import RuntimeRiskMonitor
from tools.live.secrets import SecretProvider


class TestExecutionLoopBybitRiskIntegration:
    """Integration tests for ExecutionLoop with Bybit client and risk monitor."""

    @pytest.fixture
    def mock_secret_provider(self):
        """Create mock secret provider."""
        provider = MagicMock(spec=SecretProvider)
        provider.get_api_key.return_value = "test_api_key_12345"
        provider.get_api_secret.return_value = "test_api_secret_67890"
        return provider

    @pytest.fixture
    def deterministic_clock(self):
        """Deterministic clock for testing."""
        # Use MM_FREEZE_UTC_ISO if set, otherwise fixed timestamp
        freeze_iso = os.getenv("MM_FREEZE_UTC_ISO")
        if freeze_iso:
            from datetime import datetime
            dt = datetime.fromisoformat(freeze_iso.replace("Z", "+00:00"))
            base_time_ms = int(dt.timestamp() * 1000)
        else:
            base_time_ms = 1609459200000  # 2021-01-01 00:00:00 UTC
        
        # Counter for incrementing time
        counter = [0]
        
        def clock():
            result = base_time_ms + counter[0] * 1000
            counter[0] += 1
            return result
        
        return clock

    @pytest.fixture
    def bybit_client(self, mock_secret_provider, deterministic_clock):
        """Create Bybit client for integration testing."""
        return BybitRestClient(
            secret_provider=mock_secret_provider,
            api_env="dev",
            network_enabled=False,
            clock=deterministic_clock,
            fill_rate=1.0,  # Always fill for predictable tests
            fill_latency_ms=100,
            seed=42,
        )

    @pytest.fixture
    def risk_monitor(self):
        """Create risk monitor with specific limits."""
        return RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )

    @pytest.fixture
    def execution_loop(self, bybit_client, risk_monitor, deterministic_clock):
        """Create execution loop with Bybit client."""
        order_store = InMemoryOrderStore()
        return ExecutionLoop(
            exchange=bybit_client,
            order_store=order_store,
            risk_monitor=risk_monitor,
            clock=deterministic_clock,
        )

    def test_freeze_triggers_cancel_all(self, execution_loop, deterministic_clock):
        """
        Test that freeze triggers cancel-all and produces deterministic report.
        
        Scenario:
        1. Place 2 orders (BTC, ETH)
        2. Trigger freeze (edge < threshold)
        3. Verify all orders canceled
        4. Check JSON report is deterministic
        """
        # Set MM_FREEZE_UTC_ISO for deterministic timestamps
        os.environ["MM_FREEZE_UTC_ISO"] = "2021-01-01T00:00:00Z"
        
        params = ExecutionParams(
            symbols=["BTCUSDT", "ETHUSDT"],
            iterations=5,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )
        
        # Place orders via quotes
        btc_quote = Quote(
            symbol="BTCUSDT",
            bid=49995.0,
            ask=50005.0,
            timestamp_ms=deterministic_clock(),
        )
        execution_loop.on_quote(btc_quote, params)
        
        eth_quote = Quote(
            symbol="ETHUSDT",
            bid=2999.0,
            ask=3001.0,
            timestamp_ms=deterministic_clock(),
        )
        execution_loop.on_quote(eth_quote, params)
        
        # Verify orders are open
        open_orders_before = execution_loop.exchange.get_open_orders()
        assert len(open_orders_before) > 0, "Should have open orders before freeze"
        
        # Trigger freeze with edge below threshold
        execution_loop.on_edge_update("BTCUSDT", net_bps=1.0)  # Below 1.5 threshold
        
        # Verify all orders canceled
        open_orders_after = execution_loop.exchange.get_open_orders()
        assert len(open_orders_after) == 0, "All orders should be canceled after freeze"
        
        # Check stats
        assert execution_loop.stats["freeze_events"] == 1
        assert execution_loop.stats["orders_canceled"] > 0
        
        # Generate report
        report = execution_loop._generate_report(params)
        
        # Verify report structure
        assert report["risk"]["frozen"] is True
        assert report["risk"]["freeze_events"] == 1
        assert report["orders"]["canceled"] > 0
        
        # Verify deterministic JSON output
        json_output = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
        
        # Re-generate should produce identical output
        report2 = execution_loop._generate_report(params)
        json_output2 = json.dumps(report2, sort_keys=True, separators=(",", ":")) + "\n"
        
        assert json_output == json_output2, "JSON output should be deterministic"
        
        # Cleanup
        del os.environ["MM_FREEZE_UTC_ISO"]

    def test_block_on_symbol_limit(self, execution_loop, deterministic_clock):
        """
        Test that orders are blocked when symbol notional limit is exceeded.
        
        Scenario:
        1. Set symbol limit to $10,000
        2. Fill orders totaling $9,500
        3. Attempt order for $1,000 → should be blocked
        4. Stats should show risk_blocks increment
        """
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=10,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
            base_qty=0.19,  # 0.19 * 50000 = $9,500
        )
        
        # Place and fill first order (0.19 BTC @ 50000 = $9,500)
        quote1 = Quote(
            symbol="BTCUSDT",
            bid=49995.0,
            ask=50005.0,
            timestamp_ms=deterministic_clock(),
        )
        
        initial_blocks = execution_loop.stats["risk_blocks"]
        
        # This should succeed
        execution_loop.on_quote(quote1, params)
        
        # Process fills
        execution_loop.on_fill()
        
        # Update risk monitor with fill
        execution_loop.risk_monitor.on_fill(
            symbol="BTCUSDT",
            side="Buy",
            qty=0.19,
            price=50000.0,
        )
        
        # Try to place another order (should be blocked)
        quote2 = Quote(
            symbol="BTCUSDT",
            bid=49995.0,
            ask=50005.0,
            timestamp_ms=deterministic_clock(),
        )
        
        execution_loop.on_quote(quote2, params)
        
        # Should have risk blocks now
        assert execution_loop.stats["risk_blocks"] > initial_blocks, \
            "Should have blocked orders due to symbol limit"

    def test_block_on_total_limit(self, execution_loop, deterministic_clock):
        """
        Test that orders are blocked when total notional limit is exceeded.
        
        Scenario:
        1. Set total limit to $50,000
        2. Fill BTC orders totaling $25,000
        3. Fill ETH orders totaling $24,000
        4. Attempt another order → should be blocked by total limit
        """
        params = ExecutionParams(
            symbols=["BTCUSDT", "ETHUSDT"],
            iterations=10,
            max_inventory_usd_per_symbol=30000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )
        
        initial_blocks = execution_loop.stats["risk_blocks"]
        
        # Fill BTC orders ($25,000)
        for _ in range(5):
            execution_loop.risk_monitor.on_fill(
                symbol="BTCUSDT",
                side="Buy",
                qty=0.1,
                price=50000.0,  # $5,000 per fill
            )
        
        # Fill ETH orders ($24,000)
        for _ in range(8):
            execution_loop.risk_monitor.on_fill(
                symbol="ETHUSDT",
                side="Buy",
                qty=1.0,
                price=3000.0,  # $3,000 per fill
            )
        
        # Total notional = $25,000 + $24,000 = $49,000
        # Next order should be blocked by total limit
        
        quote = Quote(
            symbol="BTCUSDT",
            bid=49995.0,
            ask=50005.0,
            timestamp_ms=deterministic_clock(),
        )
        
        execution_loop.on_quote(quote, params)
        
        # Should have risk blocks
        assert execution_loop.stats["risk_blocks"] > initial_blocks, \
            "Should have blocked orders due to total notional limit"

    def test_deterministic_report_with_freeze(self, execution_loop, deterministic_clock):
        """
        Test that report generation is fully deterministic with freeze scenario.
        
        This is the golden test for byte-for-byte comparison.
        """
        os.environ["MM_FREEZE_UTC_ISO"] = "2021-01-01T00:00:00Z"
        
        params = ExecutionParams(
            symbols=["BTCUSDT"],
            iterations=3,
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
        )
        
        # Place order
        quote = Quote(
            symbol="BTCUSDT",
            bid=49995.0,
            ask=50005.0,
            timestamp_ms=deterministic_clock(),
        )
        execution_loop.on_quote(quote, params)
        
        # Trigger freeze
        execution_loop.on_edge_update("BTCUSDT", net_bps=1.0)
        
        # Generate report twice
        report1 = execution_loop._generate_report(params)
        report2 = execution_loop._generate_report(params)
        
        json1 = json.dumps(report1, sort_keys=True, separators=(",", ":")) + "\n"
        json2 = json.dumps(report2, sort_keys=True, separators=(",", ":")) + "\n"
        
        assert json1 == json2, "Reports should be byte-for-byte identical"
        
        # Verify key fields are present
        assert "execution" in report1
        assert "orders" in report1
        assert "positions" in report1
        assert "risk" in report1
        assert report1["risk"]["frozen"] is True
        
        # Cleanup
        del os.environ["MM_FREEZE_UTC_ISO"]

    def test_no_network_calls_in_dry_run(self, bybit_client):
        """
        Verify that no network calls are made in dry-run mode.
        
        This is critical for safety - we should never hit real exchange APIs.
        """
        from tools.live.exchange import PlaceOrderRequest, Side
        
        # Attempt to place order
        request = PlaceOrderRequest(
            client_order_id="CLI00000001",
            symbol="BTCUSDT",
            side=Side.BUY,
            qty=0.1,
            price=50000.0,
        )
        
        # Should succeed without network
        response = bybit_client.place_limit_order(request)
        assert response.success is True
        assert "dry-run" in response.message.lower()
        
        # If network_enabled=True, should raise NotImplementedError
        bybit_client._network_enabled = True
        
        with pytest.raises(NotImplementedError, match="Network-enabled mode not implemented"):
            bybit_client._http_post("/test", {})


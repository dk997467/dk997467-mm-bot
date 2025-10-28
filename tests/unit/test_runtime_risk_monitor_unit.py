#!/usr/bin/env python3
"""Unit tests for tools.live.risk_monitor."""
import pytest

from tools.live.risk_monitor import RuntimeRiskMonitor


class TestRuntimeRiskMonitorBasics:
    """Test basic RuntimeRiskMonitor functionality."""
    
    def test_init_defaults(self):
        """Test initialization with default get_mark_price."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        assert monitor.max_inventory_usd_per_symbol == 10000.0
        assert monitor.max_total_notional_usd == 50000.0
        assert monitor.edge_freeze_threshold_bps == 1.5
        assert not monitor.is_frozen()
        assert monitor.blocks_total == 0
        assert monitor.freezes_total == 0
        assert monitor.last_freeze_reason is None
        assert monitor.last_freeze_symbol is None
        
        # Default get_mark_price should return 1.0
        assert monitor.get_mark_price("ANY_SYMBOL") == 1.0
    
    def test_init_custom_mark_price(self):
        """Test initialization with custom get_mark_price."""
        def custom_mark_price(symbol: str) -> float:
            prices = {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0}
            return prices.get(symbol, 1.0)
        
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
            get_mark_price=custom_mark_price
        )
        
        assert monitor.get_mark_price("BTCUSDT") == 50000.0
        assert monitor.get_mark_price("ETHUSDT") == 3000.0
        assert monitor.get_mark_price("UNKNOWN") == 1.0


class TestCheckBeforeOrder:
    """Test check_before_order method."""
    
    def test_order_allowed_within_limits(self):
        """Test order is allowed when within limits."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        # Small order well within limits
        can_place = monitor.check_before_order("BTCUSDT", "buy", 0.1, 50000.0)
        
        assert can_place is True
        assert monitor.blocks_total == 0
    
    def test_order_blocked_per_symbol_limit_buy(self):
        """Test order blocked by per-symbol limit (buy side)."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        # Order would result in position worth 10,500 USD (exceeds 10,000 limit)
        can_place = monitor.check_before_order("BTCUSDT", "buy", 0.21, 50000.0)
        
        assert can_place is False
        assert monitor.blocks_total == 1
    
    def test_order_blocked_per_symbol_limit_sell(self):
        """Test order blocked by per-symbol limit (sell side)."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        # Sell order also creates absolute notional that can exceed limit
        can_place = monitor.check_before_order("BTCUSDT", "sell", 0.21, 50000.0)
        
        assert can_place is False
        assert monitor.blocks_total == 1
    
    def test_order_blocked_total_notional_limit(self):
        """Test order blocked by total notional limit."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=15000.0,
            edge_freeze_threshold_bps=1.5,
            get_mark_price=lambda sym: {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0}.get(sym, 1.0)
        )
        
        # First order: 0.1 BTC @ 50k = 5,000 USD
        monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
        
        # Second order: 3 ETH @ 3k = 9,000 USD
        # Total would be 5,000 + 9,000 = 14,000 USD (within limits)
        can_place_eth = monitor.check_before_order("ETHUSDT", "buy", 3.0, 3000.0)
        assert can_place_eth is True, "Order within limits should be allowed"
        
        monitor.on_fill("ETHUSDT", "buy", 3.0, 3000.0)
        
        # Third order: 0.05 BTC @ 50k = 2,500 USD
        # Total would be 5,000 + 9,000 + 2,500 = 16,500 USD (exceeds 15k total limit)
        can_place_more = monitor.check_before_order("BTCUSDT", "buy", 0.05, 50000.0)
        
        assert can_place_more is False, "Order exceeding total limit should be blocked"
        assert monitor.blocks_total == 1
    
    def test_order_uses_mark_price_when_price_none(self):
        """Test order uses get_mark_price when price is None."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5,
            get_mark_price=lambda sym: 50000.0 if sym == "BTCUSDT" else 1.0
        )
        
        # Order with price=None should use mark price (50,000)
        # 0.15 * 50,000 = 7,500 USD (within 10,000 limit)
        can_place = monitor.check_before_order("BTCUSDT", "buy", 0.15, None)
        
        assert can_place is True
        assert monitor.blocks_total == 0
    
    def test_order_blocked_when_frozen(self):
        """Test order blocked when monitor is frozen."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        # Freeze monitor
        monitor.freeze("Manual freeze", "BTCUSDT")
        
        # Any order should be blocked
        can_place = monitor.check_before_order("ETHUSDT", "buy", 0.01, 3000.0)
        
        assert can_place is False
        assert monitor.blocks_total == 1
        assert monitor.is_frozen() is True


class TestOnFill:
    """Test on_fill method."""
    
    def test_on_fill_buy_updates_position(self):
        """Test on_fill correctly updates position for buy."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
        
        positions = monitor.get_positions()
        assert positions["BTCUSDT"] == 0.1
    
    def test_on_fill_sell_updates_position(self):
        """Test on_fill correctly updates position for sell."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        # First buy
        monitor.on_fill("BTCUSDT", "buy", 0.2, 50000.0)
        
        # Then sell
        monitor.on_fill("BTCUSDT", "sell", 0.1, 50000.0)
        
        positions = monitor.get_positions()
        assert positions["BTCUSDT"] == 0.1  # 0.2 - 0.1
    
    def test_on_fill_multiple_symbols(self):
        """Test on_fill tracks multiple symbols independently."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
        monitor.on_fill("ETHUSDT", "buy", 1.0, 3000.0)
        monitor.on_fill("BTCUSDT", "buy", 0.05, 50000.0)
        
        positions = monitor.get_positions()
        assert abs(positions["BTCUSDT"] - 0.15) < 1e-10  # Float precision tolerance
        assert positions["ETHUSDT"] == 1.0
    
    def test_on_fill_net_zero_position(self):
        """Test on_fill can result in net zero position."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
        monitor.on_fill("BTCUSDT", "sell", 0.1, 50000.0)
        
        positions = monitor.get_positions()
        assert positions["BTCUSDT"] == 0.0


class TestOnEdgeUpdate:
    """Test on_edge_update method."""
    
    def test_on_edge_update_above_threshold_no_freeze(self):
        """Test on_edge_update does not freeze when above threshold."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.on_edge_update("BTCUSDT", 2.0)
        
        assert not monitor.is_frozen()
        assert monitor.freezes_total == 0
        assert monitor.last_freeze_reason is None
    
    def test_on_edge_update_below_threshold_triggers_freeze(self):
        """Test on_edge_update freezes when below threshold."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.on_edge_update("BTCUSDT", 1.2)
        
        assert monitor.is_frozen()
        assert monitor.freezes_total == 1
        assert monitor.last_freeze_reason is not None
        assert "1.20 BPS" in monitor.last_freeze_reason
        assert "1.50 BPS" in monitor.last_freeze_reason
        assert monitor.last_freeze_symbol == "BTCUSDT"
    
    def test_on_edge_update_at_threshold_no_freeze(self):
        """Test on_edge_update does not freeze at exact threshold."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.on_edge_update("BTCUSDT", 1.5)
        
        assert not monitor.is_frozen()
        assert monitor.freezes_total == 0


class TestFreeze:
    """Test freeze method."""
    
    def test_freeze_sets_frozen_state(self):
        """Test freeze sets frozen state."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.freeze("Manual freeze", "BTCUSDT")
        
        assert monitor.is_frozen()
        assert monitor.freezes_total == 1
        assert monitor.last_freeze_reason == "Manual freeze"
        assert monitor.last_freeze_symbol == "BTCUSDT"
    
    def test_freeze_can_be_called_without_symbol(self):
        """Test freeze can be called without symbol."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.freeze("Global freeze")
        
        assert monitor.is_frozen()
        assert monitor.last_freeze_reason == "Global freeze"
        assert monitor.last_freeze_symbol is None
    
    def test_freeze_idempotent_increments_counter_only_once(self):
        """Test freeze increments counter only on first call."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.freeze("First freeze", "BTCUSDT")
        monitor.freeze("Second freeze", "ETHUSDT")
        
        assert monitor.is_frozen()
        assert monitor.freezes_total == 1  # Only incremented once
        assert monitor.last_freeze_reason == "Second freeze"  # Updated
        assert monitor.last_freeze_symbol == "ETHUSDT"  # Updated


class TestReset:
    """Test reset method."""
    
    def test_reset_clears_frozen_state(self):
        """Test reset clears frozen state."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.freeze("Test freeze", "BTCUSDT")
        monitor.reset()
        
        assert not monitor.is_frozen()
        assert monitor.last_freeze_reason is None
        assert monitor.last_freeze_symbol is None
    
    def test_reset_clears_positions(self):
        """Test reset clears positions."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
        monitor.on_fill("ETHUSDT", "buy", 1.0, 3000.0)
        monitor.reset()
        
        positions = monitor.get_positions()
        assert len(positions) == 0
    
    def test_reset_preserves_metrics(self):
        """Test reset does NOT reset metrics counters."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        # Generate some blocks and freezes
        monitor.freeze("Test", "BTCUSDT")
        monitor.check_before_order("ETHUSDT", "buy", 1.0, 3000.0)  # Blocked by freeze
        
        blocks_before = monitor.blocks_total
        freezes_before = monitor.freezes_total
        
        monitor.reset()
        
        # Metrics should be preserved
        assert monitor.blocks_total == blocks_before
        assert monitor.freezes_total == freezes_before
    
    def test_reset_allows_trading_again(self):
        """Test reset allows trading after freeze."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        # Freeze and verify blocked
        monitor.freeze("Test", "BTCUSDT")
        assert not monitor.check_before_order("ETHUSDT", "buy", 0.1, 3000.0)
        
        # Reset and verify allowed
        monitor.reset()
        assert monitor.check_before_order("ETHUSDT", "buy", 0.1, 3000.0)


class TestGetPositions:
    """Test get_positions method."""
    
    def test_get_positions_returns_copy(self):
        """Test get_positions returns a copy (not reference)."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=50000.0,
            edge_freeze_threshold_bps=1.5
        )
        
        monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
        
        positions1 = monitor.get_positions()
        positions2 = monitor.get_positions()
        
        # Should be equal but not the same object
        assert positions1 == positions2
        assert positions1 is not positions2
        
        # Modifying returned dict should not affect internal state
        positions1["BTCUSDT"] = 999.0
        positions3 = monitor.get_positions()
        assert positions3["BTCUSDT"] == 0.1


class TestIntegrationScenarios:
    """Test integration scenarios."""
    
    def test_full_trading_scenario(self):
        """Test full trading scenario with limits and freeze."""
        monitor = RuntimeRiskMonitor(
            max_inventory_usd_per_symbol=10000.0,
            max_total_notional_usd=20000.0,
            edge_freeze_threshold_bps=1.5,
            get_mark_price=lambda sym: {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0}.get(sym, 1.0)
        )
        
        # Step 1: Place and fill first order (allowed)
        assert monitor.check_before_order("BTCUSDT", "buy", 0.1, 50000.0)
        monitor.on_fill("BTCUSDT", "buy", 0.1, 50000.0)
        
        # Step 2: Try to place order exceeding per-symbol limit (blocked)
        assert not monitor.check_before_order("BTCUSDT", "buy", 0.15, 50000.0)
        
        # Step 3: Place order on different symbol (allowed)
        assert monitor.check_before_order("ETHUSDT", "buy", 2.0, 3000.0)
        monitor.on_fill("ETHUSDT", "buy", 2.0, 3000.0)
        
        # Step 4: Try to place order approaching total notional limit
        # Current: BTC=0.1*50k=5k, ETH=2.0*3k=6k, total=11k, limit=20k
        # New order: 3 ETH @ 3k = 9k -> new ETH position = 5*3k = 15k -> total would be 5k+15k=20k (at limit)
        can_place_more_eth = monitor.check_before_order("ETHUSDT", "buy", 3.0, 3000.0)
        
        if can_place_more_eth:
            monitor.on_fill("ETHUSDT", "buy", 3.0, 3000.0)
            # Now at or very close to limit, further orders should be blocked
            assert not monitor.check_before_order("BTCUSDT", "buy", 0.01, 50000.0)
        else:
            # If blocked, try smaller order
            assert monitor.check_before_order("ETHUSDT", "buy", 1.0, 3000.0)
        
        # Step 5: Edge degradation triggers freeze
        monitor.on_edge_update("BTCUSDT", 1.0)  # Below 1.5
        
        # Step 6: All orders blocked after freeze
        assert not monitor.check_before_order("ETHUSDT", "sell", 1.0, 3000.0)
        
        # Verify final state
        assert monitor.is_frozen()
        assert monitor.blocks_total >= 2  # At least 2 blocks
        assert monitor.freezes_total == 1
        positions = monitor.get_positions()
        assert positions["BTCUSDT"] == 0.1
        # ETH position depends on whether the 3 ETH order was allowed or not
        assert positions["ETHUSDT"] >= 2.0  # At least the initial 2 ETH


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


"""
Tests for PnL attribution functionality.

Tests:
- Maker rebate calculation
- Taker fees calculation
- Realized and unrealized PnL
- Inventory tracking
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock

from src.metrics.pnl import PnLAttributor, PnLBreakdown
from src.common.config import AppConfig


class TestPnLAttribution:
    """Test PnL attribution engine."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create mock config with nested attributes
        self.mock_config = Mock()
        self.mock_config.trading = Mock()
        self.mock_config.trading.maker_fee_bps = 1.0
        self.mock_config.trading.taker_fee_bps = 5.0
        
        # Create PnL attributor
        self.pnl_attributor = PnLAttributor(self.mock_config)
    
    def test_initialization(self):
        """Test PnL attributor initialization."""
        assert self.pnl_attributor.maker_fee_bps == 0.0001  # 1.0 / 10000
        assert self.pnl_attributor.taker_fee_bps == 0.0005  # 5.0 / 10000
        assert len(self.pnl_attributor.inventory) == 0
        assert len(self.pnl_attributor.avg_prices) == 0
        assert len(self.pnl_attributor.realized_pnl) == 0
        assert len(self.pnl_attributor.fills) == 0
    
    def test_maker_rebate_calculation(self):
        """Test maker rebate calculation."""
        # Test with different quantities and prices
        test_cases = [
            (0.001, 50000.0, "BTCUSDT"),  # Small quantity, high price
            (1.0, 100.0, "ETHUSDT"),      # Large quantity, low price
            (0.5, 1000.0, "ADAUSDT")      # Medium quantity, medium price
        ]
        
        for qty, price, symbol in test_cases:
            expected_rebate = qty * price * 0.0001
            actual_rebate = self.pnl_attributor.calculate_maker_rebate(qty, price, symbol)
            
            assert abs(actual_rebate - expected_rebate) < 1e-10
    
    def test_taker_fees_calculation(self):
        """Test taker fees calculation."""
        # Test with different quantities and prices
        test_cases = [
            (0.001, 50000.0, "BTCUSDT"),  # Small quantity, high price
            (1.0, 100.0, "ETHUSDT"),      # Large quantity, low price
            (0.5, 1000.0, "ADAUSDT")      # Medium quantity, medium price
        ]
        
        for qty, price, symbol in test_cases:
            expected_fees = qty * price * 0.0005
            actual_fees = self.pnl_attributor.calculate_taker_fees(qty, price, symbol)
            
            assert abs(actual_fees - expected_fees) < 1e-10
    
    def test_record_fill_buy(self):
        """Test recording a buy fill."""
        symbol = "BTCUSDT"
        side = "Buy"
        qty = 0.001
        price = 50000.0
        is_maker = True
        order_id = "test_order_123"
        
        # Record fill
        self.pnl_attributor.record_fill(symbol, side, qty, price, is_maker, order_id)
        
        # Check inventory
        assert symbol in self.pnl_attributor.inventory
        assert self.pnl_attributor.inventory[symbol] == qty
        
        # Check average prices
        assert symbol in self.pnl_attributor.avg_prices
        assert self.pnl_attributor.avg_prices[symbol]['Buy'] == price
        assert self.pnl_attributor.avg_prices[symbol]['Sell'] == 0.0
        
        # Check realized PnL (maker rebate)
        expected_rebate = qty * price * 0.0001
        assert abs(self.pnl_attributor.realized_pnl[symbol] - expected_rebate) < 1e-10
        
        # Check fills
        assert symbol in self.pnl_attributor.fills
        assert len(self.pnl_attributor.fills[symbol]) == 1
        
        fill_record = self.pnl_attributor.fills[symbol][0]
        assert fill_record['order_id'] == order_id
        assert fill_record['side'] == side
        assert fill_record['qty'] == qty
        assert fill_record['price'] == price
        assert fill_record['is_maker'] == is_maker
    
    def test_record_fill_sell(self):
        """Test recording a sell fill."""
        symbol = "BTCUSDT"
        side = "Sell"
        qty = 0.001
        price = 50000.0
        is_maker = True
        order_id = "test_order_456"
        
        # Record fill
        self.pnl_attributor.record_fill(symbol, side, qty, price, is_maker, order_id)
        
        # Check inventory
        assert symbol in self.pnl_attributor.inventory
        assert self.pnl_attributor.inventory[symbol] == -qty  # Negative for sell
        
        # Check average prices
        assert symbol in self.pnl_attributor.avg_prices
        assert self.pnl_attributor.avg_prices[symbol]['Buy'] == 0.0
        assert self.pnl_attributor.avg_prices[symbol]['Sell'] == price
        
        # Check realized PnL (maker rebate)
        expected_rebate = qty * price * 0.0001
        assert abs(self.pnl_attributor.realized_pnl[symbol] - expected_rebate) < 1e-10
    
    def test_multiple_fills_same_side(self):
        """Test multiple fills on the same side (weighted average)."""
        symbol = "BTCUSDT"
        side = "Buy"
        
        # First fill
        self.pnl_attributor.record_fill(symbol, side, 0.001, 50000.0, True, "order1")
        
        # Second fill
        self.pnl_attributor.record_fill(symbol, side, 0.002, 51000.0, True, "order2")
        
        # Check inventory
        assert self.pnl_attributor.inventory[symbol] == 0.003
        
        # Check weighted average price
        # (0.001 * 50000 + 0.002 * 51000) / (0.001 + 0.002) = 50666.67
        expected_avg = (0.001 * 50000 + 0.002 * 51000) / 0.003
        actual_avg = self.pnl_attributor.avg_prices[symbol]['Buy']
        
        assert abs(actual_avg - expected_avg) < 0.01
    
    def test_taker_fees_deduction(self):
        """Test that taker fees are deducted from realized PnL."""
        symbol = "BTCUSDT"
        side = "Buy"
        qty = 0.001
        price = 50000.0
        is_maker = False  # Taker fill
        order_id = "test_order_789"
        
        # Record fill
        self.pnl_attributor.record_fill(symbol, side, qty, price, is_maker, order_id)
        
        # Check realized PnL (should be negative due to fees)
        expected_fees = qty * price * 0.0005
        assert self.pnl_attributor.realized_pnl[symbol] == -expected_fees
    
    def test_unrealized_pnl_long_position(self):
        """Test unrealized PnL calculation for long position."""
        symbol = "BTCUSDT"
        
        # Create long position
        self.pnl_attributor.record_fill(symbol, "Buy", 0.001, 50000.0, True, "order1")
        
        # Test unrealized PnL at different prices
        # For inventory = 0.001 BTC:
        # Price up: (51000 - 50000) * 0.001 = 1000 * 0.001 = 1.0
        # Price down: (49000 - 50000) * 0.001 = -1000 * 0.001 = -1.0
        test_cases = [
            (51000.0, 1.0),     # Price up $1000: 0.001 * 1000 = 1.0
            (49000.0, -1.0),    # Price down $1000: 0.001 * (-1000) = -1.0
            (50000.0, 0.0),     # Same price: no unrealized PnL
        ]
        
        for current_price, expected_pnl in test_cases:
            actual_pnl = self.pnl_attributor.calculate_unrealized_pnl(symbol, current_price)
            assert abs(actual_pnl - expected_pnl) < 1e-10
    
    def test_unrealized_pnl_short_position(self):
        """Test unrealized PnL calculation for short position."""
        symbol = "BTCUSDT"
        
        # Create short position
        self.pnl_attributor.record_fill(symbol, "Sell", 0.001, 50000.0, True, "order1")
        
        # Test unrealized PnL at different prices
        # For inventory = -0.001 BTC (short):
        # Price up: (50000 - 51000) * 0.001 = -1000 * 0.001 = -1.0
        # Price down: (50000 - 49000) * 0.001 = 1000 * 0.001 = 1.0
        test_cases = [
            (51000.0, -1.0),    # Price up $1000: -0.001 * 1000 = -1.0
            (49000.0, 1.0),     # Price down $1000: -0.001 * (-1000) = 1.0
            (50000.0, 0.0),     # Same price: no unrealized PnL
        ]
        
        for current_price, expected_pnl in test_cases:
            actual_pnl = self.pnl_attributor.calculate_unrealized_pnl(symbol, current_price)
            assert abs(actual_pnl - expected_pnl) < 1e-10
    
    def test_total_pnl_calculation(self):
        """Test total PnL calculation."""
        symbol = "BTCUSDT"
        
        # Create mixed position
        self.pnl_attributor.record_fill(symbol, "Buy", 0.001, 50000.0, True, "order1")   # Maker
        self.pnl_attributor.record_fill(symbol, "Sell", 0.001, 50000.0, False, "order2")  # Taker
        
        # Calculate total PnL at current price
        current_price = 51000.0
        pnl_breakdown = self.pnl_attributor.get_total_pnl(symbol, current_price)
        
        # Check components
        assert pnl_breakdown.realized_pnl == self.pnl_attributor.realized_pnl[symbol]
        assert pnl_breakdown.unrealized_pnl == self.pnl_attributor.calculate_unrealized_pnl(symbol, current_price)
        assert pnl_breakdown.total_pnl == pnl_breakdown.realized_pnl + pnl_breakdown.unrealized_pnl
        
        # Check that total PnL matches what we expect
        expected_total = pnl_breakdown.realized_pnl + pnl_breakdown.unrealized_pnl
        assert abs(pnl_breakdown.total_pnl - expected_total) < 1e-10
    
    def test_inventory_summary(self):
        """Test inventory summary generation."""
        symbol = "BTCUSDT"
        
        # Create some fills
        self.pnl_attributor.record_fill(symbol, "Buy", 0.001, 50000.0, True, "order1")
        self.pnl_attributor.record_fill(symbol, "Sell", 0.0005, 50000.0, True, "order2")
        
        # Get summary
        summary = self.pnl_attributor.get_inventory_summary()
        
        assert symbol in summary
        symbol_summary = summary[symbol]
        
        assert symbol_summary['inventory'] == 0.0005  # 0.001 - 0.0005
        assert symbol_summary['avg_buy_price'] == 50000.0
        assert symbol_summary['avg_sell_price'] == 50000.0
        assert symbol_summary['realized_pnl'] == self.pnl_attributor.realized_pnl[symbol]
        assert symbol_summary['fill_count'] == 2
    
    def test_reset_symbol(self):
        """Test resetting PnL tracking for a symbol."""
        symbol = "BTCUSDT"
        
        # Create some data
        self.pnl_attributor.record_fill(symbol, "Buy", 0.001, 50000.0, True, "order1")
        
        # Verify data exists
        assert symbol in self.pnl_attributor.inventory
        assert symbol in self.pnl_attributor.avg_prices
        assert symbol in self.pnl_attributor.realized_pnl
        assert symbol in self.pnl_attributor.fills
        
        # Reset symbol
        self.pnl_attributor.reset_symbol(symbol)
        
        # Verify data is removed
        assert symbol not in self.pnl_attributor.inventory
        assert symbol not in self.pnl_attributor.avg_prices
        assert symbol not in self.pnl_attributor.realized_pnl
        assert symbol not in self.pnl_attributor.fills
    
    def test_metrics_update(self):
        """Test getting metrics update for Prometheus."""
        symbol = "BTCUSDT"
        
        # Create some data
        self.pnl_attributor.record_fill(symbol, "Buy", 0.001, 50000.0, True, "order1")
        
        # Get metrics update
        current_price = 51000.0
        metrics = self.pnl_attributor.get_metrics_update(symbol, current_price)
        
        # Check all required metrics are present
        required_metrics = ['maker_pnl', 'taker_fees', 'realized_pnl', 'unrealized_pnl', 'total_pnl', 'inventory']
        for metric in required_metrics:
            assert metric in metrics
        
        # Check values
        assert metrics['inventory'] == 0.001
        assert metrics['realized_pnl'] == self.pnl_attributor.realized_pnl[symbol]
        assert metrics['unrealized_pnl'] == self.pnl_attributor.calculate_unrealized_pnl(symbol, current_price)
    
    def test_pnl_breakdown_dataclass(self):
        """Test PnLBreakdown dataclass."""
        breakdown = PnLBreakdown(
            realized_pnl=1.0,
            unrealized_pnl=0.5,
            maker_rebate=0.8,
            taker_fees=0.3
        )
        
        # Check that total is calculated correctly
        expected_total = 1.0 + 0.5
        assert breakdown.total_pnl == expected_total
        
        # Check individual components
        assert breakdown.realized_pnl == 1.0
        assert breakdown.unrealized_pnl == 0.5
        assert breakdown.maker_rebate == 0.8
        assert breakdown.taker_fees == 0.3

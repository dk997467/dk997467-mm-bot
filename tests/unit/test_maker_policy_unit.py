"""
Unit tests for maker_policy module.

Tests cover:
- Post-only price calculation with offset and rounding
- Quantity rounding to step_size
- Minimum quantity checks
- Price crossing detection
- Edge cases and boundary conditions
"""

from decimal import Decimal

import pytest

from tools.live import maker_policy


class TestCalcPostOnlyPrice:
    """Tests for calc_post_only_price function."""

    def test_buy_price_below_bid(self):
        """BUY order should have price below best bid."""
        price = maker_policy.calc_post_only_price(
            side="buy",
            ref_price=50000.0,
            offset_bps=1.5,
            tick_size=0.01,
        )
        # Offset: 50000 * 0.00015 = 7.5
        # Price: 50000 - 7.5 = 49992.5, rounded down to 49992.50 (already on tick)
        assert price == Decimal("49992.50")
        assert price < Decimal("50000.0")

    def test_sell_price_above_ask(self):
        """SELL order should have price above best ask."""
        price = maker_policy.calc_post_only_price(
            side="sell",
            ref_price=50000.0,
            offset_bps=1.5,
            tick_size=0.01,
        )
        # Offset: 50000 * 0.00015 = 7.5
        # Price: 50000 + 7.5 = 50007.5, rounded up to 50007.50 (already on tick)
        assert price == Decimal("50007.50")
        assert price > Decimal("50000.0")

    def test_case_insensitive_side(self):
        """Side should be case-insensitive."""
        price_lower = maker_policy.calc_post_only_price(
            side="buy", ref_price=50000.0, offset_bps=1.5, tick_size=0.01
        )
        price_upper = maker_policy.calc_post_only_price(
            side="BUY", ref_price=50000.0, offset_bps=1.5, tick_size=0.01
        )
        assert price_lower == price_upper

    def test_different_offset_bps(self):
        """Different offsets should produce different prices."""
        price_1 = maker_policy.calc_post_only_price(
            side="buy", ref_price=50000.0, offset_bps=1.0, tick_size=0.01
        )
        price_2 = maker_policy.calc_post_only_price(
            side="buy", ref_price=50000.0, offset_bps=2.0, tick_size=0.01
        )
        # Larger offset should result in lower BUY price
        assert price_2 < price_1

    def test_different_tick_sizes(self):
        """Different tick sizes should affect rounding."""
        price_001 = maker_policy.calc_post_only_price(
            side="buy", ref_price=50000.0, offset_bps=1.5, tick_size=0.01
        )
        price_0001 = maker_policy.calc_post_only_price(
            side="buy", ref_price=50000.0, offset_bps=1.5, tick_size=0.001
        )
        # Smaller tick size allows more precision
        assert price_0001 <= price_001
        assert str(price_0001).count(".") >= 1

    def test_large_price(self):
        """Should handle large prices correctly."""
        price = maker_policy.calc_post_only_price(
            side="buy", ref_price=100000.0, offset_bps=5.0, tick_size=0.01
        )
        # Offset: 100000 * 0.0005 = 50
        # Price: 100000 - 50 = 99950, already on tick
        assert price == Decimal("99950.00")

    def test_small_price(self):
        """Should handle small prices correctly."""
        price = maker_policy.calc_post_only_price(
            side="sell", ref_price=0.001, offset_bps=10.0, tick_size=0.00001
        )
        # Offset: 0.001 * 0.001 = 0.000001
        # Price: 0.001 + 0.000001 = 0.001001, rounded up
        assert price == Decimal("0.00101")

    def test_zero_offset(self):
        """Zero offset should return reference price (rounded)."""
        price = maker_policy.calc_post_only_price(
            side="buy", ref_price=50000.0, offset_bps=0.0, tick_size=0.01
        )
        # No offset, just rounding
        assert price == Decimal("50000.00")

    def test_invalid_side(self):
        """Invalid side should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid side"):
            maker_policy.calc_post_only_price(
                side="invalid", ref_price=50000.0, offset_bps=1.5, tick_size=0.01
            )

    def test_buy_rounding_down(self):
        """BUY orders should always round DOWN."""
        # Test with a price that doesn't divide evenly
        price = maker_policy.calc_post_only_price(
            side="buy", ref_price=50000.123, offset_bps=1.0, tick_size=0.01
        )
        # Offset: 50000.123 * 0.0001 = 5.000012...
        # Price: 50000.123 - 5.000012... = 49995.122987... rounded down to 49995.12
        assert price == Decimal("49995.12")

    def test_sell_rounding_up(self):
        """SELL orders should always round UP."""
        # Test with a price that doesn't divide evenly
        price = maker_policy.calc_post_only_price(
            side="sell", ref_price=50000.123, offset_bps=1.0, tick_size=0.01
        )
        # Should be rounded up to nearest 0.01
        assert price == Decimal("50005.13")


class TestRoundQty:
    """Tests for round_qty function."""

    def test_round_down_basic(self):
        """Should round down to step_size."""
        qty = maker_policy.round_qty(0.0123456, 0.001)
        assert qty == Decimal("0.012")

    def test_round_down_two_decimals(self):
        """Should round down to 2 decimals."""
        qty = maker_policy.round_qty(1.5555, 0.01)
        assert qty == Decimal("1.55")

    def test_exact_step(self):
        """Exact multiple of step_size should not change."""
        qty = maker_policy.round_qty(1.0, 0.1)
        assert qty == Decimal("1.0")

    def test_large_qty(self):
        """Should handle large quantities."""
        qty = maker_policy.round_qty(123456.789, 0.001)
        assert qty == Decimal("123456.789")

    def test_small_qty(self):
        """Should handle small quantities."""
        qty = maker_policy.round_qty(0.00000123, 0.00000001)
        assert qty == Decimal("0.00000123")

    def test_zero_qty(self):
        """Zero quantity should remain zero."""
        qty = maker_policy.round_qty(0.0, 0.001)
        assert qty == Decimal("0.0")

    def test_step_size_one(self):
        """Step size of 1 should round to integer."""
        qty = maker_policy.round_qty(5.678, 1.0)
        assert qty == Decimal("5")

    def test_large_step_size(self):
        """Large step size should work correctly."""
        qty = maker_policy.round_qty(123.456, 10.0)
        assert qty == Decimal("120")


class TestCheckMinQty:
    """Tests for check_min_qty function."""

    def test_qty_above_min(self):
        """Quantity above minimum should pass."""
        assert maker_policy.check_min_qty(0.01, 0.001) is True

    def test_qty_equal_min(self):
        """Quantity equal to minimum should pass."""
        assert maker_policy.check_min_qty(0.001, 0.001) is True

    def test_qty_below_min(self):
        """Quantity below minimum should fail."""
        assert maker_policy.check_min_qty(0.0005, 0.001) is False

    def test_zero_qty(self):
        """Zero quantity should fail."""
        assert maker_policy.check_min_qty(0.0, 0.001) is False

    def test_large_quantities(self):
        """Large quantities should work correctly."""
        assert maker_policy.check_min_qty(1000.0, 100.0) is True
        assert maker_policy.check_min_qty(50.0, 100.0) is False

    def test_precision(self):
        """Should handle precision correctly."""
        # Test floating-point precision edge case
        assert maker_policy.check_min_qty(0.1 + 0.2, 0.3) is True


class TestCheckPriceCrossesMarket:
    """Tests for check_price_crosses_market function."""

    def test_buy_crosses_ask(self):
        """BUY at or above best_ask should cross."""
        # Buy at exactly best_ask
        assert maker_policy.check_price_crosses_market(
            side="buy", price=50010, best_bid=49990, best_ask=50010
        ) is True
        # Buy above best_ask
        assert maker_policy.check_price_crosses_market(
            side="buy", price=50020, best_bid=49990, best_ask=50010
        ) is True

    def test_buy_safe(self):
        """BUY below best_ask should be safe."""
        # Buy at best_bid is safe
        assert maker_policy.check_price_crosses_market(
            side="buy", price=49990, best_bid=49990, best_ask=50010
        ) is False
        # Buy below best_bid is safe
        assert maker_policy.check_price_crosses_market(
            side="buy", price=49980, best_bid=49990, best_ask=50010
        ) is False

    def test_sell_crosses_bid(self):
        """SELL at or below best_bid should cross."""
        # Sell at exactly best_bid
        assert maker_policy.check_price_crosses_market(
            side="sell", price=49990, best_bid=49990, best_ask=50010
        ) is True
        # Sell below best_bid
        assert maker_policy.check_price_crosses_market(
            side="sell", price=49980, best_bid=49990, best_ask=50010
        ) is True

    def test_sell_safe(self):
        """SELL above best_bid should be safe."""
        # Sell at best_ask is safe
        assert maker_policy.check_price_crosses_market(
            side="sell", price=50010, best_bid=49990, best_ask=50010
        ) is False
        # Sell above best_ask is safe
        assert maker_policy.check_price_crosses_market(
            side="sell", price=50020, best_bid=49990, best_ask=50010
        ) is False

    def test_case_insensitive(self):
        """Side should be case-insensitive."""
        result_lower = maker_policy.check_price_crosses_market(
            side="buy", price=50000, best_bid=49990, best_ask=50010
        )
        result_upper = maker_policy.check_price_crosses_market(
            side="BUY", price=50000, best_bid=49990, best_ask=50010
        )
        assert result_lower == result_upper

    def test_invalid_side(self):
        """Invalid side should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid side"):
            maker_policy.check_price_crosses_market(
                side="invalid", price=50000, best_bid=49990, best_ask=50010
            )

    def test_tight_spread(self):
        """Should handle tight spreads correctly."""
        # Spread of 0.01
        assert maker_policy.check_price_crosses_market(
            side="buy", price=50000.00, best_bid=49999.99, best_ask=50000.00
        ) is True
        assert maker_policy.check_price_crosses_market(
            side="buy", price=49999.99, best_bid=49999.99, best_ask=50000.00
        ) is False

    def test_wide_spread(self):
        """Should handle wide spreads correctly."""
        # Spread of 100
        assert maker_policy.check_price_crosses_market(
            side="buy", price=49950, best_bid=49900, best_ask=50000
        ) is False
        assert maker_policy.check_price_crosses_market(
            side="sell", price=49950, best_bid=49900, best_ask=50000
        ) is False


class TestIntegrationScenarios:
    """Integration tests for realistic scenarios."""

    def test_full_maker_only_workflow_buy(self):
        """Test full workflow for BUY order."""
        # Market: bid=49990, ask=50010
        best_bid = 49990.0
        best_ask = 50010.0
        tick_size = 0.01
        step_size = 0.00001
        min_qty = 0.00001
        min_qty_pad = 1.1
        offset_bps = 1.5

        # 1. Calculate post-only price
        price = maker_policy.calc_post_only_price(
            side="buy", ref_price=best_bid, offset_bps=offset_bps, tick_size=tick_size
        )
        assert price < Decimal(str(best_bid))

        # 2. Check price doesn't cross
        assert (
            maker_policy.check_price_crosses_market(
                side="buy", price=float(price), best_bid=best_bid, best_ask=best_ask
            )
            is False
        )

        # 3. Round quantity
        qty = 0.0123456
        rounded_qty = maker_policy.round_qty(qty, step_size)
        assert rounded_qty == Decimal("0.01234")

        # 4. Check min qty
        min_qty_required = min_qty * min_qty_pad
        assert maker_policy.check_min_qty(float(rounded_qty), min_qty_required) is True

    def test_full_maker_only_workflow_sell(self):
        """Test full workflow for SELL order."""
        # Market: bid=49990, ask=50010
        best_bid = 49990.0
        best_ask = 50010.0
        tick_size = 0.01
        step_size = 0.00001
        min_qty = 0.00001
        min_qty_pad = 1.1
        offset_bps = 1.5

        # 1. Calculate post-only price
        price = maker_policy.calc_post_only_price(
            side="sell", ref_price=best_ask, offset_bps=offset_bps, tick_size=tick_size
        )
        assert price > Decimal(str(best_ask))

        # 2. Check price doesn't cross
        assert (
            maker_policy.check_price_crosses_market(
                side="sell", price=float(price), best_bid=best_bid, best_ask=best_ask
            )
            is False
        )

        # 3. Round quantity
        qty = 0.0123456
        rounded_qty = maker_policy.round_qty(qty, step_size)
        assert rounded_qty == Decimal("0.01234")

        # 4. Check min qty
        min_qty_required = min_qty * min_qty_pad
        assert maker_policy.check_min_qty(float(rounded_qty), min_qty_required) is True

    def test_reject_qty_too_small(self):
        """Test rejection of order with quantity too small."""
        qty = 0.00005
        step_size = 0.00001
        min_qty = 0.0001
        min_qty_pad = 1.1

        # Round quantity
        rounded_qty = maker_policy.round_qty(qty, step_size)
        assert rounded_qty == Decimal("0.00005")

        # Check min qty should fail
        min_qty_required = min_qty * min_qty_pad
        assert maker_policy.check_min_qty(float(rounded_qty), min_qty_required) is False

    def test_reject_price_crosses_market(self):
        """Test rejection when price would cross market."""
        # Market: bid=49990, ask=50010
        best_bid = 49990.0
        best_ask = 50010.0
        tick_size = 0.01

        # Try to buy at best_ask (would cross)
        price = maker_policy.calc_post_only_price(
            side="buy", ref_price=best_ask, offset_bps=0.0, tick_size=tick_size
        )
        # Should cross market
        assert (
            maker_policy.check_price_crosses_market(
                side="buy", price=float(price), best_bid=best_bid, best_ask=best_ask
            )
            is True
        )


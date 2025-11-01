"""
Tests for repricer floating-point rounding with tick-safe operations.

Verifies that repricer always produces valid tick-aligned prices with
no cross-mid violations.
"""
import pytest
from decimal import Decimal
from hypothesis import given, strategies as st, assume, settings

from src.common.price_ticks import (
    compute_bid_ask,
    is_multiple_of_tick,
    to_ticks,
    from_ticks,
    floor_to_tick,
    ceil_to_tick
)


# Strategies for repricer scenarios
mids = st.decimals(min_value='1000', max_value='100000', places=6)
tick_sizes_repricer = st.sampled_from([
    Decimal('0.01'),   # Common for forex/stable pairs
    Decimal('0.1'),    # Mid-range
    Decimal('0.5'),    # BTC on some exchanges
    Decimal('1'),      # Round numbers
    Decimal('5')       # Large ticks
])
spread_ticks_repricer = st.integers(min_value=1, max_value=20)
k_ticks_repricer = st.integers(min_value=3, max_value=15)


class TestRepricerBasicInvariants:
    """Test basic repricer invariants."""
    
    @pytest.mark.parametrize("mid,tick,spread_ticks", [
        (Decimal('50000'), Decimal('0.5'), 2),
        (Decimal('50000'), Decimal('0.5'), 5),
        (Decimal('50000'), Decimal('0.01'), 10),
        (Decimal('3000'), Decimal('0.1'), 3),
        (Decimal('1000'), Decimal('0.01'), 5),
    ])
    def test_no_cross_mid(self, mid, tick, spread_ticks):
        """Test that bid <= mid <= ask always."""
        bid, ask = compute_bid_ask(mid, spread_ticks, tick)
        
        assert bid <= mid, f"Bid > mid: {bid} > {mid}"
        assert ask >= mid, f"Ask < mid: {ask} < {mid}"
        assert bid <= ask, f"Bid > ask: {bid} > {ask}"
    
    @pytest.mark.parametrize("mid,tick,spread_ticks", [
        (Decimal('50000'), Decimal('0.5'), 2),
        (Decimal('50000'), Decimal('0.01'), 10),
        (Decimal('3000'), Decimal('0.1'), 3),
    ])
    def test_min_spread_enforced(self, mid, tick, spread_ticks):
        """Test minimum spread of 1 tick."""
        bid, ask = compute_bid_ask(mid, spread_ticks, tick)
        
        spread = ask - bid
        assert spread >= tick, f"Spread < tick: {spread} < {tick}"
    
    @pytest.mark.parametrize("mid,tick,spread_ticks", [
        (Decimal('50000'), Decimal('0.5'), 2),
        (Decimal('50000'), Decimal('0.01'), 10),
        (Decimal('3000'), Decimal('0.1'), 3),
    ])
    def test_both_multiples_of_tick(self, mid, tick, spread_ticks):
        """Test that bid and ask are multiples of tick."""
        bid, ask = compute_bid_ask(mid, spread_ticks, tick)
        
        assert is_multiple_of_tick(bid, tick), f"Bid not multiple: {bid} % {tick}"
        assert is_multiple_of_tick(ask, tick), f"Ask not multiple: {ask} % {tick}"


class TestRepricerNearTickBoundaries:
    """Test repricer behavior near tick boundaries."""
    
    @pytest.mark.parametrize("offset", [
        Decimal('0'),           # Exact multiple
        Decimal('0.000001'),    # Just above
        Decimal('-0.000001'),   # Just below
        Decimal('0.0001'),      # Small offset
        Decimal('-0.0001'),
    ])
    def test_mid_near_boundary(self, offset):
        """Test mid price near tick boundaries."""
        tick = Decimal('0.5')
        mid = Decimal('50000') + offset  # Near exact multiple
        spread_ticks = 2
        
        bid, ask = compute_bid_ask(mid, spread_ticks, tick)
        
        # Verify invariants
        assert bid <= mid <= ask
        assert ask - bid >= tick
        assert is_multiple_of_tick(bid, tick)
        assert is_multiple_of_tick(ask, tick)
    
    @pytest.mark.parametrize("mid_base,tick", [
        (Decimal('50000'), Decimal('0.5')),
        (Decimal('50000'), Decimal('0.01')),
        (Decimal('3000'), Decimal('0.1')),
    ])
    def test_mid_at_half_tick(self, mid_base, tick):
        """Test mid price at half-tick (between ticks)."""
        mid = mid_base + tick / 2  # Exactly between two ticks
        spread_ticks = 4
        
        bid, ask = compute_bid_ask(mid, spread_ticks, tick)
        
        # Should still satisfy invariants
        assert bid <= mid <= ask
        assert ask - bid >= tick
        assert is_multiple_of_tick(bid, tick)
        assert is_multiple_of_tick(ask, tick)


class TestRepricerPropertyBased:
    """Property-based tests for repricer."""
    
    @given(
        mid=mids,
        tick_size=tick_sizes_repricer,
        spread_ticks=spread_ticks_repricer,
        k_ticks=k_ticks_repricer
    )
    @settings(max_examples=5000)
    def test_repricer_invariants_always_hold(self, mid, tick_size, spread_ticks, k_ticks):
        """Property: repricer invariants always hold."""
        bid, ask = compute_bid_ask(mid, spread_ticks, tick_size, k_ticks)
        
        # Invariant 1: No cross-mid
        assert bid <= mid <= ask, f"Cross-mid: {bid} > {mid} or {ask} < {mid}"
        
        # Invariant 2: Minimum spread
        assert ask - bid >= tick_size, f"Spread too narrow: {ask - bid} < {tick_size}"
        
        # Invariant 3: Multiples of tick
        assert is_multiple_of_tick(bid, tick_size), f"Bid not multiple: {bid}"
        assert is_multiple_of_tick(ask, tick_size), f"Ask not multiple: {ask}"
    
    @given(
        mid=mids,
        tick_size=tick_sizes_repricer,
        spread_ticks=spread_ticks_repricer,
        k_ticks=k_ticks_repricer
    )
    @settings(max_examples=2000)
    def test_repricer_spreads_symmetric_when_possible(self, mid, tick_size, spread_ticks, k_ticks):
        """Test that spreads are approximately symmetric when k_ticks allows."""
        # Only test when spread fits within k_ticks
        assume(spread_ticks <= k_ticks)
        
        bid, ask = compute_bid_ask(mid, spread_ticks, tick_size, k_ticks)
        
        # Measure distances
        bid_distance = mid - bid
        ask_distance = ask - mid
        
        # Should be approximately symmetric (within a few ticks)
        asymmetry = abs(bid_distance - ask_distance)
        max_asymmetry = tick_size * 3  # Allow up to 3 ticks asymmetry
        
        assert asymmetry <= max_asymmetry, f"Too asymmetric: {bid_distance} vs {ask_distance}"
    
    @given(
        mid=mids,
        tick_size=tick_sizes_repricer,
        k_ticks=k_ticks_repricer
    )
    @settings(max_examples=1000)
    def test_min_spread_always_one_tick(self, mid, tick_size, k_ticks):
        """Property: minimum spread is always 1 tick even if requested 0."""
        bid, ask = compute_bid_ask(mid, spread_ticks=0, tick_size=tick_size, k_ticks=k_ticks)
        
        assert ask - bid >= tick_size


class TestRepricerTickArithmetic:
    """Test repricer using pure integer tick arithmetic."""
    
    def test_tick_arithmetic_bid_ask(self):
        """Test computing bid/ask in ticks."""
        mid = Decimal('50000')
        tick = Decimal('0.5')
        spread_ticks = 4
        
        # Convert to ticks
        mid_ticks = to_ticks(mid, tick)  # 100000
        
        # Compute bid/ask in ticks
        half_spread = spread_ticks // 2  # 2
        bid_ticks = mid_ticks - half_spread  # 99998
        ask_ticks = mid_ticks + half_spread  # 100002
        
        # Convert back
        bid = from_ticks(bid_ticks, tick)  # 49999.0
        ask = from_ticks(ask_ticks, tick)  # 50001.0
        
        # Verify
        assert bid == Decimal('49999.0')
        assert ask == Decimal('50001.0')
        assert ask - bid == Decimal('2.0')  # 4 ticks * 0.5
    
    def test_tick_arithmetic_no_drift(self):
        """Test that tick arithmetic has no float drift."""
        mid = Decimal('50000')
        tick = Decimal('0.01')
        
        # Compute bid/ask many times
        for _ in range(1000):
            bid, ask = compute_bid_ask(mid, spread_ticks=10, tick_size=tick)
            
            # Use bid as new mid (simulating price movement)
            mid = bid
        
        # After 1000 iterations, should still be exact multiple
        assert is_multiple_of_tick(mid, tick)


class TestRepricerEdgeCases:
    """Test repricer edge cases."""
    
    def test_very_narrow_spread(self):
        """Test spread of exactly 1 tick."""
        mid = Decimal('50000')
        tick = Decimal('0.5')
        
        bid, ask = compute_bid_ask(mid, spread_ticks=1, tick_size=tick)
        
        # With spread_ticks=1, we get minimum 1 tick spread
        # But the algorithm may widen to ensure bid <= mid <= ask
        assert ask - bid >= tick
        assert bid <= mid <= ask
    
    def test_very_wide_spread(self):
        """Test very wide spread (50 ticks)."""
        mid = Decimal('50000')
        tick = Decimal('0.5')
        k_ticks = 30  # Allow wide spread
        
        bid, ask = compute_bid_ask(mid, spread_ticks=50, tick_size=tick, k_ticks=k_ticks)
        
        assert bid <= mid <= ask
        assert is_multiple_of_tick(bid, tick)
        assert is_multiple_of_tick(ask, tick)
    
    def test_clamp_constrains_wide_spread(self):
        """Test that k_ticks clamps wide spreads."""
        mid = Decimal('50000')
        tick = Decimal('1')
        k_ticks = 5  # Max 5 ticks from mid
        
        bid, ask = compute_bid_ask(mid, spread_ticks=20, tick_size=tick, k_ticks=k_ticks)
        
        # Should be clamped to k_ticks
        assert abs(to_ticks(mid, tick) - to_ticks(bid, tick)) <= k_ticks
        assert abs(to_ticks(ask, tick) - to_ticks(mid, tick)) <= k_ticks
    
    def test_odd_spread_ticks(self):
        """Test odd number of spread ticks."""
        mid = Decimal('50000')
        tick = Decimal('0.5')
        
        bid, ask = compute_bid_ask(mid, spread_ticks=5, tick_size=tick)
        
        # Should still satisfy invariants
        assert bid <= mid <= ask
        assert ask - bid >= tick
        assert is_multiple_of_tick(bid, tick)
        assert is_multiple_of_tick(ask, tick)
    
    def test_mid_not_on_tick(self):
        """Test mid price that's not on a tick boundary."""
        mid = Decimal('50000.123')  # Not multiple of 0.5
        tick = Decimal('0.5')
        
        bid, ask = compute_bid_ask(mid, spread_ticks=4, tick_size=tick)
        
        # Should still work and satisfy invariants
        assert bid <= mid <= ask
        assert is_multiple_of_tick(bid, tick)
        assert is_multiple_of_tick(ask, tick)


class TestRepricerDirectionalRounding:
    """Test directional rounding for bids vs asks."""
    
    def test_bid_rounds_down(self):
        """Test that bid uses floor (rounds down)."""
        price = Decimal('50000.7')
        tick = Decimal('0.5')
        
        bid_price = floor_to_tick(price, tick)
        
        assert bid_price == Decimal('50000.5')  # Floored
        assert bid_price <= price
    
    def test_ask_rounds_up(self):
        """Test that ask uses ceil (rounds up)."""
        price = Decimal('50000.3')
        tick = Decimal('0.5')
        
        ask_price = ceil_to_tick(price, tick)
        
        assert ask_price == Decimal('50000.5')  # Ceiled
        assert ask_price >= price
    
    def test_directional_rounding_prevents_cross(self):
        """Test that directional rounding prevents crossing mid."""
        mid = Decimal('50000.25')  # Between ticks
        tick = Decimal('0.5')
        
        # If we naively round, we might cross mid
        # But with directional rounding + invariants, we don't
        bid, ask = compute_bid_ask(mid, spread_ticks=2, tick_size=tick)
        
        assert bid <= mid <= ask


class TestRepricerRealWorldScenarios:
    """Test real-world repricer scenarios."""
    
    @pytest.mark.parametrize("symbol,mid,tick,spread_ticks", [
        ("BTCUSDT", Decimal('67890.5'), Decimal('0.1'), 5),
        ("ETHUSDT", Decimal('3456.78'), Decimal('0.01'), 10),
        ("SOLUSDT", Decimal('123.45'), Decimal('0.01'), 8),
        ("BTCUSDT", Decimal('100000'), Decimal('1'), 3),
    ])
    def test_realistic_pairs(self, symbol, mid, tick, spread_ticks):
        """Test realistic trading pair scenarios."""
        bid, ask = compute_bid_ask(mid, spread_ticks, tick)
        
        # All invariants must hold
        assert bid <= mid <= ask
        assert ask - bid >= tick
        assert is_multiple_of_tick(bid, tick)
        assert is_multiple_of_tick(ask, tick)
        
        # Log for verification
        print(f"\n{symbol}: mid={mid}, tick={tick}")
        print(f"  bid={bid}, ask={ask}, spread={ask-bid}")
    
    def test_high_volatility_wide_spread(self):
        """Test wide spread during high volatility."""
        mid = Decimal('50000')
        tick = Decimal('0.5')
        spread_ticks = 30  # Wide spread
        k_ticks = 40  # Allow it
        
        bid, ask = compute_bid_ask(mid, spread_ticks, tick, k_ticks)
        
        # Should handle wide spread correctly
        assert bid <= mid <= ask
        assert ask - bid >= tick
        assert is_multiple_of_tick(bid, tick)
        assert is_multiple_of_tick(ask, tick)
    
    def test_low_volatility_tight_spread(self):
        """Test tight spread during low volatility."""
        mid = Decimal('50000')
        tick = Decimal('0.01')
        spread_ticks = 2  # Tight spread
        k_ticks = 10
        
        bid, ask = compute_bid_ask(mid, spread_ticks, tick, k_ticks)
        
        # Should handle tight spread correctly
        assert bid <= mid <= ask
        assert ask - bid >= tick
        assert is_multiple_of_tick(bid, tick)
        assert is_multiple_of_tick(ask, tick)


class TestRepricerStressTests:
    """Stress tests for repricer."""
    
    @given(
        mid=st.decimals(min_value='0.01', max_value='1000000', places=8),
        tick_size=st.sampled_from([
            Decimal('0.000001'), Decimal('0.0001'), Decimal('0.01'),
            Decimal('0.1'), Decimal('1'), Decimal('10')
        ]),
        spread_ticks=st.integers(min_value=1, max_value=100),
        k_ticks=st.integers(min_value=1, max_value=50)
    )
    @settings(max_examples=10000)
    def test_repricer_never_violates_invariants(self, mid, tick_size, spread_ticks, k_ticks):
        """Stress test: invariants NEVER violated across 10k cases."""
        bid, ask = compute_bid_ask(mid, spread_ticks, tick_size, k_ticks)
        
        # MUST satisfy all invariants
        assert bid <= mid <= ask, f"CRITICAL: Cross-mid violation"
        assert ask - bid >= tick_size, f"CRITICAL: Spread < tick"
        assert is_multiple_of_tick(bid, tick_size), f"CRITICAL: Bid not multiple"
        assert is_multiple_of_tick(ask, tick_size), f"CRITICAL: Ask not multiple"


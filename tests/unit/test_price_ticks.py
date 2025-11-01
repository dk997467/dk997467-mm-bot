"""
Property-based tests for tick-safe price operations.

Uses Hypothesis to test across wide range of inputs and verify invariants.
"""
import pytest
from decimal import Decimal
from hypothesis import given, strategies as st, assume, settings

from src.common.price_ticks import (
    to_ticks,
    from_ticks,
    floor_to_tick,
    ceil_to_tick,
    round_to_tick,
    clamp_to_mid,
    compute_bid_ask,
    is_multiple_of_tick,
    register_tick_size,
    get_tick_size,
    clear_tick_size_cache,
    PriceError,
    TickSizeError,
    _to_decimal
)


# Hypothesis strategies
prices = st.one_of(
    st.decimals(min_value='0.000001', max_value='10000000', places=6),
    st.floats(min_value=1e-6, max_value=1e7, allow_nan=False, allow_infinity=False)
)

tick_sizes = st.sampled_from([
    Decimal('0.000001'),
    Decimal('0.0001'),
    Decimal('0.001'),
    Decimal('0.01'),
    Decimal('0.1'),
    Decimal('0.5'),
    Decimal('1'),
    Decimal('5'),
    Decimal('10')
])

spread_ticks_st = st.integers(min_value=1, max_value=50)
k_ticks_st = st.integers(min_value=1, max_value=20)


class TestBasicConversions:
    """Test basic tick conversions."""
    
    def test_to_ticks_simple(self):
        """Test simple tick conversion."""
        assert to_ticks(Decimal('100'), Decimal('0.5')) == 200
        assert to_ticks(Decimal('100.5'), Decimal('0.5')) == 201
        assert to_ticks(Decimal('100.25'), Decimal('0.5')) == 201  # Rounds to nearest (half-up)
    
    def test_from_ticks_simple(self):
        """Test simple tick to price conversion."""
        assert from_ticks(200, Decimal('0.5')) == Decimal('100.0')
        assert from_ticks(201, Decimal('0.5')) == Decimal('100.5')
    
    def test_floor_to_tick_simple(self):
        """Test floor to tick."""
        assert floor_to_tick(Decimal('100.7'), Decimal('0.5')) == Decimal('100.5')
        assert floor_to_tick(Decimal('100.5'), Decimal('0.5')) == Decimal('100.5')
        assert floor_to_tick(Decimal('100.3'), Decimal('0.5')) == Decimal('100.0')
    
    def test_ceil_to_tick_simple(self):
        """Test ceil to tick."""
        assert ceil_to_tick(Decimal('100.3'), Decimal('0.5')) == Decimal('100.5')
        assert ceil_to_tick(Decimal('100.5'), Decimal('0.5')) == Decimal('100.5')
        assert ceil_to_tick(Decimal('100.7'), Decimal('0.5')) == Decimal('101.0')
    
    def test_round_to_tick_simple(self):
        """Test round to nearest tick."""
        assert round_to_tick(Decimal('100.2'), Decimal('0.5')) == Decimal('100.0')
        assert round_to_tick(Decimal('100.3'), Decimal('0.5')) == Decimal('100.5')
        assert round_to_tick(Decimal('100.7'), Decimal('0.5')) == Decimal('100.5')  # 100.7 / 0.5 = 201.4 → 201


class TestErrorHandling:
    """Test error handling."""
    
    def test_zero_tick_size(self):
        """Test that zero tick size raises error."""
        with pytest.raises(TickSizeError):
            to_ticks(Decimal('100'), Decimal('0'))
    
    def test_negative_tick_size(self):
        """Test that negative tick size raises error."""
        with pytest.raises(TickSizeError):
            to_ticks(Decimal('100'), Decimal('-0.5'))
    
    def test_nan_price(self):
        """Test that NaN price raises error."""
        with pytest.raises(PriceError):
            _to_decimal(float('nan'))
    
    def test_inf_price(self):
        """Test that infinite price raises error."""
        with pytest.raises(PriceError):
            _to_decimal(float('inf'))


class TestPropertyBasedRoundTrip:
    """Property-based tests for round-trip conversions."""
    
    @given(ticks=st.integers(min_value=0, max_value=1000000), tick_size=tick_sizes)
    @settings(max_examples=1000)
    def test_ticks_round_trip(self, ticks, tick_size):
        """Property: to_ticks(from_ticks(n, t), t) == n"""
        price = from_ticks(ticks, tick_size)
        recovered_ticks = to_ticks(price, tick_size)
        
        assert recovered_ticks == ticks, f"Round-trip failed: {ticks} -> {price} -> {recovered_ticks}"
    
    @given(price=prices, tick_size=tick_sizes)
    @settings(max_examples=1000)
    def test_price_round_trip_is_multiple(self, price, tick_size):
        """Property: from_ticks(to_ticks(p, t), t) is exact multiple of t"""
        ticks = to_ticks(price, tick_size)
        recovered_price = from_ticks(ticks, tick_size)
        
        # Recovered price must be multiple of tick
        assert is_multiple_of_tick(recovered_price, tick_size)
    
    @given(price=prices, tick_size=tick_sizes)
    @settings(max_examples=1000)
    def test_floor_is_multiple(self, price, tick_size):
        """Property: floor_to_tick result is exact multiple"""
        floored = floor_to_tick(price, tick_size)
        assert is_multiple_of_tick(floored, tick_size)
    
    @given(price=prices, tick_size=tick_sizes)
    @settings(max_examples=1000)
    def test_ceil_is_multiple(self, price, tick_size):
        """Property: ceil_to_tick result is exact multiple"""
        ceiled = ceil_to_tick(price, tick_size)
        assert is_multiple_of_tick(ceiled, tick_size)


class TestPropertyBasedMonotonicity:
    """Property-based tests for monotonicity."""
    
    @given(price=prices, tick_size=tick_sizes)
    @settings(max_examples=500)
    def test_floor_monotonic(self, price, tick_size):
        """Property: floor_to_tick is monotonic"""
        price_dec = Decimal(str(price))
        assume(price_dec > tick_size)  # Avoid edge cases near zero
        
        floored1 = floor_to_tick(price_dec, tick_size)
        floored2 = floor_to_tick(price_dec + tick_size, tick_size)
        
        assert floored2 >= floored1, f"floor not monotonic: {floored1} vs {floored2}"
    
    @given(price=prices, tick_size=tick_sizes)
    @settings(max_examples=500)
    def test_ceil_monotonic(self, price, tick_size):
        """Property: ceil_to_tick is monotonic"""
        price_dec = Decimal(str(price))
        assume(price_dec > tick_size)
        
        ceiled1 = ceil_to_tick(price_dec, tick_size)
        ceiled2 = ceil_to_tick(price_dec + tick_size, tick_size)
        
        assert ceiled2 >= ceiled1, f"ceil not monotonic: {ceiled1} vs {ceiled2}"


class TestPropertyBasedInvariants:
    """Property-based tests for invariants."""
    
    @given(price=prices, tick_size=tick_sizes)
    @settings(max_examples=1000)
    def test_floor_less_equal_price(self, price, tick_size):
        """Property: floor_to_tick(p) <= p"""
        price_dec = Decimal(str(price))
        floored = floor_to_tick(price_dec, tick_size)
        
        assert floored <= price_dec, f"floor > price: {floored} > {price_dec}"
    
    @given(price=prices, tick_size=tick_sizes)
    @settings(max_examples=1000)
    def test_ceil_greater_equal_price(self, price, tick_size):
        """Property: ceil_to_tick(p) >= p"""
        price_dec = Decimal(str(price))
        ceiled = ceil_to_tick(price_dec, tick_size)
        
        assert ceiled >= price_dec, f"ceil < price: {ceiled} < {price_dec}"
    
    @given(price=prices, tick_size=tick_sizes)
    @settings(max_examples=1000)
    def test_floor_ceil_distance(self, price, tick_size):
        """Property: ceil(p) - floor(p) <= tick_size"""
        price_dec = Decimal(str(price))
        floored = floor_to_tick(price_dec, tick_size)
        ceiled = ceil_to_tick(price_dec, tick_size)
        
        distance = ceiled - floored
        assert distance <= tick_size, f"ceil - floor > tick: {distance} > {tick_size}"


class TestPropertyBasedBidAsk:
    """Property-based tests for bid/ask computation."""
    
    @given(
        mid=st.decimals(min_value='100', max_value='100000', places=4),
        spread_ticks=spread_ticks_st,
        tick_size=tick_sizes,
        k_ticks=k_ticks_st
    )
    @settings(max_examples=2000)
    def test_bid_ask_no_cross_mid(self, mid, spread_ticks, tick_size, k_ticks):
        """Property: bid <= mid <= ask (no cross-mid)"""
        bid, ask = compute_bid_ask(mid, spread_ticks, tick_size, k_ticks)
        
        assert bid <= mid <= ask, f"Cross-mid: {bid} > {mid} or {ask} < {mid}"
    
    @given(
        mid=st.decimals(min_value='100', max_value='100000', places=4),
        spread_ticks=spread_ticks_st,
        tick_size=tick_sizes,
        k_ticks=k_ticks_st
    )
    @settings(max_examples=2000)
    def test_bid_ask_min_spread(self, mid, spread_ticks, tick_size, k_ticks):
        """Property: ask - bid >= tick_size"""
        bid, ask = compute_bid_ask(mid, spread_ticks, tick_size, k_ticks)
        
        spread = ask - bid
        assert spread >= tick_size, f"Spread too narrow: {spread} < {tick_size}"
    
    @given(
        mid=st.decimals(min_value='100', max_value='100000', places=4),
        spread_ticks=spread_ticks_st,
        tick_size=tick_sizes,
        k_ticks=k_ticks_st
    )
    @settings(max_examples=2000)
    def test_bid_ask_multiples_of_tick(self, mid, spread_ticks, tick_size, k_ticks):
        """Property: bid and ask are exact multiples of tick_size"""
        bid, ask = compute_bid_ask(mid, spread_ticks, tick_size, k_ticks)
        
        assert is_multiple_of_tick(bid, tick_size), f"Bid not multiple: {bid} % {tick_size}"
        assert is_multiple_of_tick(ask, tick_size), f"Ask not multiple: {ask} % {tick_size}"
    
    @given(
        mid=st.decimals(min_value='100', max_value='100000', places=4),
        spread_ticks=spread_ticks_st,
        tick_size=tick_sizes,
        k_ticks=k_ticks_st
    )
    @settings(max_examples=1000)
    def test_bid_ask_within_k_ticks(self, mid, spread_ticks, tick_size, k_ticks):
        """Property: |bid - mid| <= k_ticks * tick, |ask - mid| <= k_ticks * tick"""
        # Skip if spread is wider than k_ticks allows
        assume(spread_ticks <= k_ticks * 2)
        
        bid, ask = compute_bid_ask(mid, spread_ticks, tick_size, k_ticks)
        
        mid_dec = Decimal(str(mid))
        
        # Convert to ticks for accurate comparison
        mid_ticks = to_ticks(mid_dec, tick_size)
        bid_ticks = to_ticks(bid, tick_size)
        ask_ticks = to_ticks(ask, tick_size)
        
        bid_distance_ticks = abs(bid_ticks - mid_ticks)
        ask_distance_ticks = abs(ask_ticks - mid_ticks)
        
        # Allow 1 extra tick for rounding
        assert bid_distance_ticks <= k_ticks + 1, f"Bid too far: {bid_distance_ticks} > {k_ticks}"
        assert ask_distance_ticks <= k_ticks + 1, f"Ask too far: {ask_distance_ticks} > {k_ticks}"


class TestPropertyBasedClamp:
    """Property-based tests for clamp_to_mid."""
    
    @given(
        price=prices,
        mid=prices,
        k_ticks=k_ticks_st,
        tick_size=tick_sizes
    )
    @settings(max_examples=1000)
    def test_clamp_distance(self, price, mid, k_ticks, tick_size):
        """Property: |clamped - mid| <= k_ticks * tick_size"""
        price_dec = Decimal(str(price))
        mid_dec = Decimal(str(mid))
        
        clamped = clamp_to_mid(price_dec, mid_dec, k_ticks, tick_size)
        
        # Compare in ticks for accuracy
        mid_ticks = to_ticks(mid_dec, tick_size)
        clamped_ticks = to_ticks(clamped, tick_size)
        
        distance_ticks = abs(clamped_ticks - mid_ticks)
        
        assert distance_ticks <= k_ticks, f"Clamp failed: {distance_ticks} ticks > {k_ticks} ticks"
    
    @given(
        price=prices,
        mid=prices,
        k_ticks=k_ticks_st,
        tick_size=tick_sizes
    )
    @settings(max_examples=1000)
    def test_clamp_is_multiple(self, price, mid, k_ticks, tick_size):
        """Property: clamped result is multiple of tick_size"""
        price_dec = Decimal(str(price))
        mid_dec = Decimal(str(mid))
        
        clamped = clamp_to_mid(price_dec, mid_dec, k_ticks, tick_size)
        
        assert is_multiple_of_tick(clamped, tick_size)


class TestEdgeCases:
    """Test edge cases."""
    
    def test_very_small_tick(self):
        """Test with very small tick size."""
        tick = Decimal('0.000001')
        price = Decimal('50000.123456')
        
        ticks = to_ticks(price, tick)
        recovered = from_ticks(ticks, tick)
        
        assert is_multiple_of_tick(recovered, tick)
    
    def test_very_large_price(self):
        """Test with very large price."""
        tick = Decimal('1')
        price = Decimal('9999999')
        
        ticks = to_ticks(price, tick)
        recovered = from_ticks(ticks, tick)
        
        assert is_multiple_of_tick(recovered, tick)
    
    def test_exact_multiple(self):
        """Test price that's exactly a multiple."""
        tick = Decimal('0.5')
        price = Decimal('100.0')
        
        floored = floor_to_tick(price, tick)
        ceiled = ceil_to_tick(price, tick)
        
        assert floored == price
        assert ceiled == price
    
    def test_ulp_below_multiple(self):
        """Test price just below exact multiple (ULP edge)."""
        tick = Decimal('0.5')
        price = Decimal('100.0') - Decimal('0.0000000001')  # Just below
        
        floored = floor_to_tick(price, tick)
        ceiled = ceil_to_tick(price, tick)
        
        assert floored == Decimal('99.5')
        assert ceiled == Decimal('100.0')
    
    def test_ulp_above_multiple(self):
        """Test price just above exact multiple (ULP edge)."""
        tick = Decimal('0.5')
        price = Decimal('100.0') + Decimal('0.0000000001')  # Just above
        
        floored = floor_to_tick(price, tick)
        ceiled = ceil_to_tick(price, tick)
        
        assert floored == Decimal('100.0')
        assert ceiled == Decimal('100.5')
    
    def test_zero_spread_bumped_to_one(self):
        """Test that zero spread is bumped to 1 tick."""
        mid = Decimal('50000')
        tick = Decimal('0.5')
        
        bid, ask = compute_bid_ask(mid, spread_ticks=0, tick_size=tick)
        
        assert ask - bid >= tick


class TestSymbolTickSizes:
    """Test per-symbol tick size management."""
    
    def setup_method(self):
        """Clear cache before each test."""
        clear_tick_size_cache()
    
    def test_register_and_get(self):
        """Test registering and retrieving tick sizes."""
        register_tick_size("BTCUSDT", Decimal('0.5'))
        register_tick_size("ETHUSDT", Decimal('0.01'))
        
        assert get_tick_size("BTCUSDT") == Decimal('0.5')
        assert get_tick_size("ETHUSDT") == Decimal('0.01')
    
    def test_fallback(self):
        """Test fallback for unknown symbol."""
        tick = get_tick_size("UNKNOWN", fallback=Decimal('0.1'))
        assert tick == Decimal('0.1')
    
    def test_no_fallback_raises(self):
        """Test that no fallback raises error."""
        with pytest.raises(TickSizeError):
            get_tick_size("UNKNOWN", fallback=None)


class TestIntegerTickArithmetic:
    """Test that integer tick arithmetic avoids float drift."""
    
    def test_no_float_drift_large_numbers(self):
        """Test no float drift with large numbers."""
        tick = Decimal('0.01')
        
        # Accumulate 1000 ticks
        total_ticks = 0
        for i in range(1000):
            total_ticks += 1
        
        price = from_ticks(total_ticks, tick)
        
        # Should be exactly 10.00, no drift
        assert price == Decimal('10.00')
    
    def test_no_float_drift_many_operations(self):
        """Test no drift across many operations."""
        tick = Decimal('0.001')
        price = Decimal('50000')
        
        # Convert back and forth many times
        for _ in range(100):
            ticks = to_ticks(price, tick)
            price = from_ticks(ticks, tick)
        
        # Should still be exactly 50000
        assert price == Decimal('50000.000')


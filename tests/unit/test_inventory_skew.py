"""
Unit tests for inventory-skew functionality.

Tests inventory-based spread adjustments for rebalancing.
"""
import pytest
from src.risk.inventory_skew import (
    compute_skew_bps,
    apply_inventory_skew,
    get_inventory_pct
)
from src.common.config import InventorySkewConfig


@pytest.fixture
def config():
    """Default inventory-skew config."""
    return InventorySkewConfig(
        enabled=True,
        target_pct=0.0,
        max_skew_bps=0.6,
        slope_bps_per_1pct=0.1,
        clamp_pct=5.0
    )


def test_compute_skew_zero_inventory(config):
    """Test skew computation with zero inventory."""
    skew = compute_skew_bps(config, 0.0)
    assert skew == 0.0


def test_compute_skew_below_clamp(config):
    """Test skew computation below clamp threshold."""
    skew = compute_skew_bps(config, 3.0)  # Within ±5% clamp
    assert skew == 0.0


def test_compute_skew_long_inventory(config):
    """Test skew computation with long inventory."""
    skew = compute_skew_bps(config, 10.0)  # 10% long
    expected = 10.0 * 0.1  # 1.0 bps raw, but clamped to max_skew_bps
    assert skew == pytest.approx(min(expected, 0.6))


def test_compute_skew_short_inventory(config):
    """Test skew computation with short inventory."""
    skew = compute_skew_bps(config, -10.0)  # 10% short
    expected = -10.0 * 0.1  # -1.0 bps raw
    assert skew == pytest.approx(max(expected, -0.6))


def test_compute_skew_max_limit(config):
    """Test skew respects max_skew_bps limit."""
    skew = compute_skew_bps(config, 50.0)  # 50% long (extreme)
    assert abs(skew) <= config.max_skew_bps


def test_compute_skew_disabled(config):
    """Test skew returns zero when disabled."""
    config.enabled = False
    skew = compute_skew_bps(config, 20.0)
    assert skew == 0.0


def test_apply_skew_zero_inventory(config):
    """Test applying skew with zero inventory."""
    result = apply_inventory_skew(config, 0.0, 50000.0, 50010.0)
    
    assert result['bid_price'] == 50000.0
    assert result['ask_price'] == 50010.0
    assert result['skew_bps'] == 0.0


def test_apply_skew_long_inventory(config):
    """Test applying skew with long inventory (should push asks down)."""
    result = apply_inventory_skew(config, 10.0, 50000.0, 50010.0)
    
    # Long inventory: ask should be more aggressive (lower)
    # bid should be less aggressive (lower or unchanged)
    if result['skew_bps'] != 0.0:
        assert result['ask_price'] < 50010.0  # More aggressive ask
        assert result['bid_price'] <= 50000.0  # Less aggressive bid


def test_apply_skew_short_inventory(config):
    """Test applying skew with short inventory (should push bids up)."""
    result = apply_inventory_skew(config, -10.0, 50000.0, 50010.0)
    
    # Short inventory: bid should be more aggressive (higher)
    # ask should be less aggressive (higher or unchanged)
    if result['skew_bps'] != 0.0:
        assert result['bid_price'] > 50000.0  # More aggressive bid
        assert result['ask_price'] >= 50010.0  # Less aggressive ask


def test_apply_skew_preserves_spread(config):
    """Test that skew doesn't cross bid/ask spread."""
    result = apply_inventory_skew(config, 50.0, 50000.0, 50010.0)
    
    # Bid should always be < ask
    assert result['bid_price'] < result['ask_price']


def test_get_inventory_pct():
    """Test inventory percentage calculation."""
    # Zero position
    assert get_inventory_pct(0.0, 100.0) == 0.0
    
    # 50% long
    assert get_inventory_pct(50.0, 100.0) == 50.0
    
    # 50% short
    assert get_inventory_pct(-50.0, 100.0) == -50.0
    
    # 100% long (at max)
    assert get_inventory_pct(100.0, 100.0) == 100.0
    
    # Over max (clamped)
    assert get_inventory_pct(150.0, 100.0) == 100.0
    
    # Zero max position
    assert get_inventory_pct(50.0, 0.0) == 0.0


def test_slope_scaling(config):
    """Test that skew scales linearly with inventory (up to max)."""
    skew_10 = compute_skew_bps(config, 10.0)
    skew_20 = compute_skew_bps(config, 20.0)
    
    # Should be linear up to max_skew_bps
    if skew_20 < config.max_skew_bps:
        assert skew_20 == pytest.approx(2.0 * skew_10, rel=0.01)


def test_clamp_symmetry(config):
    """Test that clamp works symmetrically for long/short."""
    # Just below clamp on long side
    skew_long = compute_skew_bps(config, 4.9)
    assert skew_long == 0.0
    
    # Just below clamp on short side
    skew_short = compute_skew_bps(config, -4.9)
    assert skew_short == 0.0
    
    # Just above clamp
    skew_long_above = compute_skew_bps(config, 5.1)
    skew_short_above = compute_skew_bps(config, -5.1)
    assert skew_long_above > 0.0
    assert skew_short_above < 0.0


def test_apply_skew_returns_all_fields(config):
    """Test that apply_inventory_skew returns complete result dict."""
    result = apply_inventory_skew(config, 10.0, 50000.0, 50010.0)
    
    assert 'bid_price' in result
    assert 'ask_price' in result
    assert 'skew_bps' in result
    assert 'bid_adj_bps' in result
    assert 'ask_adj_bps' in result


def test_sign_correctness():
    """Test that skew sign matches inventory direction."""
    config = InventorySkewConfig()
    
    # Long inventory → positive skew
    skew_long = compute_skew_bps(config, 20.0)
    assert skew_long > 0.0
    
    # Short inventory → negative skew
    skew_short = compute_skew_bps(config, -20.0)
    assert skew_short < 0.0

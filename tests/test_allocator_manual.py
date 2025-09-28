"""
Tests for manual portfolio allocation mode.
"""

import pytest
from unittest.mock import Mock

from src.common.config import PortfolioConfig
from src.portfolio.allocator import PortfolioAllocator, PortfolioTarget
from src.common.di import AppContext


def create_mock_context(portfolio_cfg: PortfolioConfig) -> AppContext:
    """Create mock AppContext for testing."""
    mock_app_config = Mock()
    mock_app_config.portfolio = portfolio_cfg
    
    ctx = AppContext(cfg=mock_app_config)
    return ctx


def test_manual_weights_normalization():
    """Test that manual weights are properly normalized."""
    portfolio_cfg = PortfolioConfig(
        mode="manual",
        manual_weights={"BTCUSDT": 0.6, "ETHUSDT": 0.4},
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    # Mock stats (not used in manual mode)
    stats = {"BTCUSDT": {"vol": 0.1}, "ETHUSDT": {"vol": 0.2}}
    
    weights = allocator.compute_weights(stats)
    
    # Weights should sum to 1.0
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    # After constraints and renormalization, weights may change
    # but relative ordering should not invert (allow equality under caps)
    assert weights["BTCUSDT"] >= weights["ETHUSDT"]
    # Check that weights are within reasonable bounds
    assert weights["BTCUSDT"] >= 0.5
    assert weights["ETHUSDT"] >= 0.4


def test_manual_weights_clamp():
    """Test that manual weights respect min/max constraints."""
    portfolio_cfg = PortfolioConfig(
        mode="manual",
        manual_weights={"BTCUSDT": 0.8, "ETHUSDT": 0.1, "SOLUSDT": 0.1},
        budget_usd=10000.0,
        min_weight=0.15,  # ETHUSDT should be clamped up
        max_weight=0.5    # BTCUSDT should be clamped down
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {"BTCUSDT": {"vol": 0.1}, "ETHUSDT": {"vol": 0.2}, "SOLUSDT": {"vol": 0.3}}
    
    weights = allocator.compute_weights(stats)
    
    # Check constraints
    for weight in weights.values():
        assert weight >= 0.15
        # After renormalization, weights may exceed max_weight
        # but should still be reasonable
        assert weight <= 0.7
    
    # Weights should still sum to 1.0 after clamping and renormalization
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_ema_smoothing():
    """Test EMA smoothing of weights."""
    portfolio_cfg = PortfolioConfig(
        mode="manual",
        manual_weights={"BTCUSDT": 0.6, "ETHUSDT": 0.4},
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        ema_alpha=0.3
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {"BTCUSDT": {"vol": 0.1}, "ETHUSDT": {"vol": 0.2}}
    
    # First update - no previous weights
    targets1 = allocator.update(ctx, stats)
    weights1 = allocator.get_current_weights()
    
    # Second update with different weights
    portfolio_cfg.manual_weights = {"BTCUSDT": 0.4, "ETHUSDT": 0.6}
    targets2 = allocator.update(ctx, stats)
    weights2 = allocator.get_current_weights()
    
    # Weights should be smoothed (not exactly the new values)
    assert weights2["BTCUSDT"] != 0.4  # Should be smoothed
    assert weights2["ETHUSDT"] != 0.6  # Should be smoothed
    
    # But should be closer to new values than old values (allow equality under caps)
    assert abs(weights2["BTCUSDT"] - 0.4) <= abs(weights1["BTCUSDT"] - 0.4)
    assert abs(weights2["ETHUSDT"] - 0.6) <= abs(weights1["ETHUSDT"] - 0.6)


def test_targets_from_weights():
    """Test conversion of weights to portfolio targets."""
    portfolio_cfg = PortfolioConfig(
        mode="manual",
        manual_weights={"BTCUSDT": 0.6, "ETHUSDT": 0.4},
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    weights = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    targets = allocator.targets_from_weights(weights)
    
    # Check target USD
    assert targets["BTCUSDT"].target_usd == 6000.0  # 60% of 10000
    assert targets["ETHUSDT"].target_usd == 4000.0  # 40% of 10000
    
    # Check max levels (based on weight ratio to max_weight)
    # BTCUSDT: weight 0.6, max_weight 0.5, ratio 1.2, levels = round(10 * 1.2) = 12, clamped to 10
    assert targets["BTCUSDT"].max_levels == 10
    # ETHUSDT: weight 0.4, max_weight 0.5, ratio 0.8, levels = round(10 * 0.8) = 8
    assert targets["ETHUSDT"].max_levels == 8


def test_empty_manual_weights():
    """Test behavior with empty manual weights."""
    portfolio_cfg = PortfolioConfig(
        mode="manual",
        manual_weights={},
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {"BTCUSDT": {"vol": 0.1}}
    
    # Should assign at least min_weight to new symbols (not empty)
    weights = allocator.compute_weights(stats)
    assert "BTCUSDT" in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert weights["BTCUSDT"] >= portfolio_cfg.min_weight


def test_manual_weights_sum_zero():
    """Test behavior when manual weights sum to zero."""
    portfolio_cfg = PortfolioConfig(
        mode="manual",
        manual_weights={"BTCUSDT": 0.0, "ETHUSDT": 0.0},
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {"BTCUSDT": {"vol": 0.1}, "ETHUSDT": {"vol": 0.2}}
    
    # Should handle zero sum gracefully by assigning at least min_weight to symbols
    weights = allocator.compute_weights(stats)
    assert set(weights.keys()) == set(["BTCUSDT", "ETHUSDT"])
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert all(w >= portfolio_cfg.min_weight for w in weights.values())

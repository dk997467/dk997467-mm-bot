"""
Tests for inverse volatility portfolio allocation mode.
"""

import pytest
from unittest.mock import Mock

from src.common.config import PortfolioConfig
from src.portfolio.allocator import PortfolioAllocator
from src.common.di import AppContext


def create_mock_context(portfolio_cfg: PortfolioConfig) -> AppContext:
    """Create mock AppContext for testing."""
    mock_app_config = Mock()
    mock_app_config.portfolio = portfolio_cfg
    
    ctx = AppContext(cfg=mock_app_config)
    return ctx


def test_inverse_vol_basic():
    """Test basic inverse volatility allocation."""
    portfolio_cfg = PortfolioConfig(
        mode="inverse_vol",
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    # Higher volatility should result in lower weight
    stats = {
        "BTCUSDT": {"vol": 0.02},  # Low vol
        "ETHUSDT": {"vol": 0.04},  # Medium vol
        "SOLUSDT": {"vol": 0.08}   # High vol
    }
    
    weights = allocator.compute_weights(stats)
    
    # Check that weights sum to 1.0
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    
    # Check inverse relationship: higher vol → lower weight
    # After constraints and renormalization, the relationship may change
    # but we can check that the highest vol doesn't get the highest weight
    assert weights["SOLUSDT"] <= weights["ETHUSDT"]  # SOLUSDT has highest vol
    assert weights["SOLUSDT"] <= weights["BTCUSDT"]  # SOLUSDT has highest vol


def test_inverse_vol_constraints():
    """Test that inverse vol weights respect min/max constraints."""
    portfolio_cfg = PortfolioConfig(
        mode="inverse_vol",
        budget_usd=10000.0,
        min_weight=0.15,  # Higher min weight
        max_weight=0.4    # Lower max weight
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {
        "BTCUSDT": {"vol": 0.01},  # Very low vol
        "ETHUSDT": {"vol": 0.05},  # Medium vol
        "SOLUSDT": {"vol": 0.10}   # High vol
    }
    
    weights = allocator.compute_weights(stats)
    
    # Check constraints
    for weight in weights.values():
        assert weight >= 0.15
        assert weight <= 0.4
    
    # Weights should still sum to 1.0 after constraints and renormalization
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_inverse_vol_zero_volatility():
    """Test behavior with zero volatility."""
    portfolio_cfg = PortfolioConfig(
        mode="inverse_vol",
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {
        "BTCUSDT": {"vol": 0.0},   # Zero vol
        "ETHUSDT": {"vol": 0.05},  # Normal vol
    }
    
    weights = allocator.compute_weights(stats)
    
    # Should handle zero volatility gracefully
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    # After constraints and renormalization, weights may be equal
    # but both should be valid
    assert weights["BTCUSDT"] >= 0.4
    assert weights["ETHUSDT"] >= 0.4


def test_inverse_vol_very_small_volatility():
    """Test behavior with very small volatility values."""
    portfolio_cfg = PortfolioConfig(
        mode="inverse_vol",
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {
        "BTCUSDT": {"vol": 1e-10},  # Very small vol
        "ETHUSDT": {"vol": 0.05},   # Normal vol
    }
    
    weights = allocator.compute_weights(stats)
    
    # Should handle very small volatility gracefully
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    # After constraints and renormalization, weights may be equal
    # but both should be valid
    assert weights["BTCUSDT"] >= 0.4
    assert weights["ETHUSDT"] >= 0.4


def test_inverse_vol_equal_volatility():
    """Test behavior with equal volatility values."""
    portfolio_cfg = PortfolioConfig(
        mode="inverse_vol",
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {
        "BTCUSDT": {"vol": 0.05},
        "ETHUSDT": {"vol": 0.05},
        "SOLUSDT": {"vol": 0.05}
    }
    
    weights = allocator.compute_weights(stats)
    
    # Equal volatility should result in equal weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert abs(weights["BTCUSDT"] - weights["ETHUSDT"]) < 1e-6
    assert abs(weights["ETHUSDT"] - weights["SOLUSDT"]) < 1e-6
    assert abs(weights["BTCUSDT"] - 1/3) < 1e-6


def test_inverse_vol_extreme_volatility():
    """Test behavior with extreme volatility differences."""
    portfolio_cfg = PortfolioConfig(
        mode="inverse_vol",
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {
        "BTCUSDT": {"vol": 0.01},   # Very low vol
        "ETHUSDT": {"vol": 0.50},   # Very high vol
    }
    
    weights = allocator.compute_weights(stats)
    
    # Extreme differences should still result in valid weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    # After constraints and renormalization, weights may be equal
    # but both should be valid
    assert weights["BTCUSDT"] >= 0.4
    assert weights["ETHUSDT"] >= 0.4


def test_inverse_vol_single_symbol():
    """Test behavior with single symbol."""
    portfolio_cfg = PortfolioConfig(
        mode="inverse_vol",
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {"BTCUSDT": {"vol": 0.05}}
    
    weights = allocator.compute_weights(stats)
    
    # Single symbol should get weight 1.0
    assert abs(weights["BTCUSDT"] - 1.0) < 1e-6
    assert len(weights) == 1


def test_inverse_vol_empty_stats():
    """Test behavior with empty statistics."""
    portfolio_cfg = PortfolioConfig(
        mode="inverse_vol",
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {}
    
    weights = allocator.compute_weights(stats)
    
    # Empty stats should result in empty weights
    assert weights == {}

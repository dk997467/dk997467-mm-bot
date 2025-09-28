"""
Tests for portfolio targets and level calculations.
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


def test_targets_from_weights_basic():
    """Test basic target calculation from weights."""
    portfolio_cfg = PortfolioConfig(
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
    
    # Check max levels
    assert targets["BTCUSDT"].max_levels == 10  # weight 0.6 > max_weight 0.5, so max levels
    assert targets["ETHUSDT"].max_levels == 8   # weight 0.4 < max_weight 0.5, so proportional


def test_targets_levels_constraints():
    """Test that levels respect min/max constraints."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=3,   # Higher min
        levels_per_side_max=8    # Lower max
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    weights = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    targets = allocator.targets_from_weights(weights)
    
    # Check level constraints
    for target in targets.values():
        assert target.max_levels >= 3
        assert target.max_levels <= 8


def test_targets_levels_proportional():
    """Test that levels are proportional to weights."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    weights = {"BTCUSDT": 0.3, "ETHUSDT": 0.2, "SOLUSDT": 0.1}
    targets = allocator.targets_from_weights(weights)
    
    # Check proportional relationship
    # BTCUSDT: weight 0.3, max_weight 0.5, ratio 0.6, levels = round(10 * 0.6) = 6
    assert targets["BTCUSDT"].max_levels == 6
    
    # ETHUSDT: weight 0.2, max_weight 0.5, ratio 0.4, levels = round(10 * 0.4) = 4
    assert targets["ETHUSDT"].max_levels == 4
    
    # SOLUSDT: weight 0.1, max_weight 0.5, ratio 0.2, levels = round(10 * 0.2) = 2
    assert targets["SOLUSDT"].max_levels == 2


def test_targets_levels_rounding():
    """Test that levels are properly rounded."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    # Weights that will result in fractional level calculations
    weights = {"BTCUSDT": 0.35, "ETHUSDT": 0.25, "SOLUSDT": 0.15}
    targets = allocator.targets_from_weights(weights)
    
    # Check that levels are integers
    for target in targets.values():
        assert isinstance(target.max_levels, int)
        assert target.max_levels >= 1
        assert target.max_levels <= 10


def test_targets_budget_scaling():
    """Test that targets scale with budget."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=5000.0,  # Half budget
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    weights = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    targets = allocator.targets_from_weights(weights)
    
    # Check that targets scale with budget
    assert targets["BTCUSDT"].target_usd == 3000.0  # 60% of 5000
    assert targets["ETHUSDT"].target_usd == 2000.0  # 40% of 5000
    
    # Levels should remain the same (not budget-dependent)
    assert targets["BTCUSDT"].max_levels == 10
    assert targets["ETHUSDT"].max_levels == 8


def test_targets_weight_edge_cases():
    """Test target calculation with edge case weights."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    # Test with weights at boundaries
    weights = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}  # Both at max_weight
    targets = allocator.targets_from_weights(weights)
    
    # Both should get max levels
    assert targets["BTCUSDT"].max_levels == 10
    assert targets["ETHUSDT"].max_levels == 10
    
    # Test with very small weights
    weights = {"BTCUSDT": 0.02, "ETHUSDT": 0.98}  # One at min_weight
    targets = allocator.targets_from_weights(weights)
    
    # Min weight should get min levels
    assert targets["BTCUSDT"].max_levels == 1
    # Max weight should get max levels
    assert targets["ETHUSDT"].max_levels == 10


def test_targets_empty_weights():
    """Test target calculation with empty weights."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    weights = {}
    targets = allocator.targets_from_weights(weights)
    
    # Empty weights should result in empty targets
    assert targets == {}


def test_targets_single_weight():
    """Test target calculation with single weight."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    weights = {"BTCUSDT": 1.0}
    targets = allocator.targets_from_weights(weights)
    
    # Single weight should get full budget and max levels
    assert targets["BTCUSDT"].target_usd == 10000.0
    assert targets["BTCUSDT"].max_levels == 10


def test_targets_levels_ratio_calculation():
    """Test the exact level ratio calculation."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.3,  # Lower max_weight for clearer testing
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    weights = {"BTCUSDT": 0.15, "ETHUSDT": 0.09, "SOLUSDT": 0.06}
    targets = allocator.targets_from_weights(weights)
    
    # Check exact calculations:
    # BTCUSDT: weight 0.15, max_weight 0.3, ratio 0.5, levels = round(10 * 0.5) = 5
    assert targets["BTCUSDT"].max_levels == 5
    
    # ETHUSDT: weight 0.09, max_weight 0.3, ratio 0.3, levels = round(10 * 0.3) = 3
    assert targets["ETHUSDT"].max_levels == 3
    
    # SOLUSDT: weight 0.06, max_weight 0.3, ratio 0.2, levels = round(10 * 0.2) = 2
    assert targets["SOLUSDT"].max_levels == 2

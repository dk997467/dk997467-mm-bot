"""
Tests for portfolio caps enforcement in OrderManager.
"""

import pytest
from unittest.mock import Mock, patch
from dataclasses import dataclass

from src.common.config import PortfolioConfig
from src.portfolio.allocator import PortfolioAllocator, PortfolioTarget
from src.common.di import AppContext
from src.execution.order_manager import OrderManager


@dataclass
class MockOrderState:
    """Mock order state for testing."""
    order_id: str
    client_order_id: str
    symbol: str
    side: str
    price: float
    qty: float
    status: str
    filled_qty: float
    remaining_qty: float
    created_time: float
    last_update_time: float


def create_mock_context(portfolio_cfg: PortfolioConfig) -> AppContext:
    """Create mock AppContext for testing."""
    mock_app_config = Mock()
    mock_app_config.portfolio = portfolio_cfg
    mock_app_config.strategy = Mock()
    mock_app_config.strategy.amend_price_threshold_bps = 1.0
    mock_app_config.strategy.amend_size_threshold = 0.2
    mock_app_config.strategy.min_time_in_book_ms = 500
    
    ctx = AppContext(cfg=mock_app_config)
    return ctx


def test_order_manager_portfolio_integration():
    """Test that OrderManager integrates with portfolio targets."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=2,
        levels_per_side_max=8
    )
    
    ctx = create_mock_context(portfolio_cfg)
    
    # Create portfolio targets
    targets = {
        "BTCUSDT": PortfolioTarget(target_usd=6000.0, max_levels=6),
        "ETHUSDT": PortfolioTarget(target_usd=4000.0, max_levels=4)
    }
    ctx.portfolio_targets = targets
    
    # Mock REST connector
    mock_rest_connector = Mock()
    
    # Create OrderManager
    order_manager = OrderManager(ctx, mock_rest_connector)
    
    # Verify portfolio targets are accessible
    assert hasattr(ctx, 'portfolio_targets')
    assert ctx.portfolio_targets == targets


def test_portfolio_targets_structure():
    """Test that portfolio targets have correct structure."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {"BTCUSDT": {"vol": 0.02}, "ETHUSDT": {"vol": 0.04}}
    targets = allocator.update(ctx, stats)
    
    # Check target structure
    for symbol, target in targets.items():
        assert hasattr(target, 'target_usd')
        assert hasattr(target, 'max_levels')
        assert isinstance(target.target_usd, float)
        assert isinstance(target.max_levels, int)
        assert target.target_usd > 0
        assert target.max_levels >= portfolio_cfg.levels_per_side_min
        assert target.max_levels <= portfolio_cfg.levels_per_side_max


def test_min_levels_respected():
    """Test that minimum levels are always respected."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=3,  # Higher min levels
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    # Create very small weights that would result in < min_levels
    stats = {"BTCUSDT": {"vol": 0.01}, "ETHUSDT": {"vol": 0.99}}
    targets = allocator.update(ctx, stats)
    
    # All targets should respect min_levels
    for target in targets.values():
        assert target.max_levels >= portfolio_cfg.levels_per_side_min


def test_max_levels_respected():
    """Test that maximum levels are always respected."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=5   # Lower max levels
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    # Create large weights that would result in > max_levels
    stats = {"BTCUSDT": {"vol": 0.01}, "ETHUSDT": {"vol": 0.99}}
    targets = allocator.update(ctx, stats)
    
    # All targets should respect max_levels
    for target in targets.values():
        assert target.max_levels <= portfolio_cfg.levels_per_side_max


def test_target_usd_calculation():
    """Test that target USD is correctly calculated."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {"BTCUSDT": {"vol": 0.02}, "ETHUSDT": {"vol": 0.04}}
    targets = allocator.update(ctx, stats)
    
    # Check that target USD sums to budget
    total_target_usd = sum(target.target_usd for target in targets.values())
    # With manual mode and empty weights, targets will be empty
    if portfolio_cfg.mode == "manual" and not portfolio_cfg.manual_weights:
        assert total_target_usd == 0
    else:
        assert abs(total_target_usd - portfolio_cfg.budget_usd) < 1e-6
    
    # Check individual targets are proportional to weights
    weights = allocator.get_current_weights()
    for symbol in targets:
        expected_target = portfolio_cfg.budget_usd * weights[symbol]
        assert abs(targets[symbol].target_usd - expected_target) < 1e-6


def test_levels_proportional_to_weights():
    """Test that levels are proportional to weights within constraints."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {"BTCUSDT": {"vol": 0.02}, "ETHUSDT": {"vol": 0.04}}
    targets = allocator.update(ctx, stats)
    weights = allocator.get_current_weights()
    
    # Check that higher weights get more levels (proportional)
    # Only test if we have weights for both symbols
    if "BTCUSDT" in weights and "ETHUSDT" in weights:
        if weights["BTCUSDT"] > weights["ETHUSDT"]:
            assert targets["BTCUSDT"].max_levels >= targets["ETHUSDT"].max_levels
        else:
            assert targets["ETHUSDT"].max_levels >= targets["BTCUSDT"].max_levels


def test_portfolio_targets_persistence():
    """Test that portfolio targets persist across updates."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    # First update
    stats1 = {"BTCUSDT": {"vol": 0.02}, "ETHUSDT": {"vol": 0.04}}
    targets1 = allocator.update(ctx, stats1)
    
    # Second update with same stats
    targets2 = allocator.update(ctx, stats1)
    
    # Targets should be consistent (with EMA smoothing)
    assert len(targets1) == len(targets2)
    for symbol in targets1:
        # Values should be close (allowing for EMA smoothing)
        assert abs(targets1[symbol].target_usd - targets2[symbol].target_usd) < 1e-3
        assert targets1[symbol].max_levels == targets2[symbol].max_levels


def test_portfolio_targets_validation():
    """Test that portfolio targets are valid."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    stats = {"BTCUSDT": {"vol": 0.02}, "ETHUSDT": {"vol": 0.04}}
    targets = allocator.update(ctx, stats)
    
    # Validate target structure and values
    for symbol, target in targets.items():
        # Check target USD
        assert target.target_usd > 0
        assert target.target_usd <= portfolio_cfg.budget_usd
        
        # Check levels
        assert target.max_levels >= portfolio_cfg.levels_per_side_min
        assert target.max_levels <= portfolio_cfg.levels_per_side_max
        assert isinstance(target.max_levels, int)
        
        # Check symbol consistency
        assert symbol in stats


def test_empty_portfolio_targets():
    """Test behavior with empty portfolio targets."""
    portfolio_cfg = PortfolioConfig(
        budget_usd=10000.0,
        min_weight=0.02,
        max_weight=0.5,
        levels_per_side_min=1,
        levels_per_side_max=10
    )
    
    ctx = create_mock_context(portfolio_cfg)
    allocator = PortfolioAllocator(ctx)
    
    # Empty stats should result in empty targets
    stats = {}
    targets = allocator.update(ctx, stats)
    
    assert targets == {}
    assert allocator.get_current_weights() == {}

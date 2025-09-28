"""
E2E test for allocator + PositionSkewGuard integration.

Tests freeze_symbols and bias_color effects on sizing.
"""

import pytest
from types import SimpleNamespace
from typing import Dict
from unittest.mock import Mock

from src.portfolio.allocator import PortfolioAllocator
from src.common.config import AppConfig, PosSkewConfig, GuardsConfig, AllocatorConfig, AllocatorSmoothingConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


def test_allocator_pos_skew_freeze_and_bias():
    """Test that freeze_symbols prevents sizing and bias_color reduces magnitude."""
    
    # Setup config with pos_skew limits and bias_cap
    pos_skew_config = PosSkewConfig(
        per_symbol_abs_limit=0.1,  # BTCUSDT=0.15 > 0.1 -> breach
        per_color_abs_limit=0.15   # blue total=0.20 > 0.15 -> breach
    )
    guards_config = GuardsConfig(pos_skew=pos_skew_config)
    
    allocator_config = AllocatorConfig(
        smoothing=AllocatorSmoothingConfig(bias_cap=0.10)
    )
    
    app_config = AppConfig(
        guards=guards_config,
        allocator=allocator_config
    )
    
    # Mock context with positions and colors
    mock_ctx = Mock(spec=AppContext)
    mock_ctx.cfg = app_config
    
    # Positions: BTCUSDT=0.15 (breach), ETHUSDT=0.05 (no breach)
    # Colors: both "blue" -> total=0.20 > 0.15 (breach)
    mock_state = SimpleNamespace()
    mock_state.positions_by_symbol = {"BTCUSDT": 0.15, "ETHUSDT": 0.05}
    mock_state.color_by_symbol = {"BTCUSDT": "blue", "ETHUSDT": "blue"}
    mock_ctx.state = mock_state
    
    # Mock metrics
    mock_metrics = Mock(spec=Metrics)
    mock_metrics.record_position_skew_breach = Mock()
    mock_ctx.metrics = mock_metrics
    
    # Create allocator
    allocator = PortfolioAllocator(mock_ctx)
    
    # Input weights: both symbols want full allocation
    weights = {"BTCUSDT": 1.0, "ETHUSDT": 1.0}
    
    # Call targets_from_weights
    targets = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    
    # Assertions
    assert "BTCUSDT" in targets
    assert "ETHUSDT" in targets
    
    # BTCUSDT should be frozen (target_usd == 0.0)
    btc_target = targets["BTCUSDT"].target_usd
    assert btc_target == 0.0, f"BTCUSDT should be frozen, got target_usd={btc_target}"
    
    # ETHUSDT should be reduced but > 0 (bias applied)
    eth_target = targets["ETHUSDT"].target_usd
    assert eth_target > 0.0, f"ETHUSDT should have positive target after bias, got target_usd={eth_target}"
    assert eth_target < 1000.0, f"ETHUSDT should be reduced by bias, got target_usd={eth_target}"  # Less than full allocation
    assert eth_target >= 900.0, f"ETHUSDT bias should be small (5-10%), got target_usd={eth_target}"  # Around 5-10% reduction
    
    # Verify metrics were called
    mock_metrics.record_position_skew_breach.assert_called_once()
    call_args = mock_metrics.record_position_skew_breach.call_args[0]
    symbol_breach, color_breach = call_args
    
    assert "BTCUSDT" in symbol_breach
    assert "ETHUSDT" not in symbol_breach
    assert color_breach is True


def test_allocator_pos_skew_no_breach():
    """Test that no breach results in normal allocation."""
    
    # Setup config with high limits (no breach)
    pos_skew_config = PosSkewConfig(
        per_symbol_abs_limit=1.0,  # Higher than any position
        per_color_abs_limit=1.0    # Higher than total
    )
    guards_config = GuardsConfig(pos_skew=pos_skew_config)
    
    allocator_config = AllocatorConfig(
        smoothing=AllocatorSmoothingConfig(bias_cap=0.10)
    )
    
    app_config = AppConfig(
        guards=guards_config,
        allocator=allocator_config
    )
    
    # Mock context
    mock_ctx = Mock(spec=AppContext)
    mock_ctx.cfg = app_config
    
    # Small positions (no breach)
    mock_state = SimpleNamespace()
    mock_state.positions_by_symbol = {"BTCUSDT": 0.05, "ETHUSDT": 0.03}
    mock_state.color_by_symbol = {"BTCUSDT": "blue", "ETHUSDT": "red"}
    mock_ctx.state = mock_state
    
    # Mock metrics
    mock_metrics = Mock(spec=Metrics)
    mock_metrics.record_position_skew_breach = Mock()
    mock_ctx.metrics = mock_metrics
    
    # Create allocator
    allocator = PortfolioAllocator(mock_ctx)
    
    # Input weights
    weights = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}
    
    # Call targets_from_weights
    targets = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    
    # Assertions: normal allocation (no freezing/bias)
    assert "BTCUSDT" in targets
    assert "ETHUSDT" in targets
    
    btc_target = targets["BTCUSDT"].target_usd
    eth_target = targets["ETHUSDT"].target_usd
    
    # Should be proportional to weights (approximately)
    assert btc_target > 0.0
    assert eth_target > 0.0
    assert btc_target > eth_target  # 0.6 > 0.4
    
    # No breach metrics should be recorded
    mock_metrics.record_position_skew_breach.assert_not_called()


def test_allocator_pos_skew_disabled():
    """Test that disabled limits (0.0) result in normal allocation."""
    
    # Setup config with disabled limits
    pos_skew_config = PosSkewConfig(
        per_symbol_abs_limit=0.0,  # Disabled
        per_color_abs_limit=0.0    # Disabled
    )
    guards_config = GuardsConfig(pos_skew=pos_skew_config)
    
    allocator_config = AllocatorConfig(
        smoothing=AllocatorSmoothingConfig(bias_cap=0.10)
    )
    
    app_config = AppConfig(
        guards=guards_config,
        allocator=allocator_config
    )
    
    # Mock context
    mock_ctx = Mock(spec=AppContext)
    mock_ctx.cfg = app_config
    
    # Large positions (would breach if enabled)
    mock_state = SimpleNamespace()
    mock_state.positions_by_symbol = {"BTCUSDT": 10.0, "ETHUSDT": 5.0}
    mock_state.color_by_symbol = {"BTCUSDT": "blue", "ETHUSDT": "blue"}
    mock_ctx.state = mock_state
    
    # Mock metrics
    mock_metrics = Mock(spec=Metrics)
    mock_metrics.record_position_skew_breach = Mock()
    mock_ctx.metrics = mock_metrics
    
    # Create allocator
    allocator = PortfolioAllocator(mock_ctx)
    
    # Input weights
    weights = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    
    # Call targets_from_weights
    targets = allocator.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    
    # Assertions: normal allocation (limits disabled)
    assert "BTCUSDT" in targets
    assert "ETHUSDT" in targets
    
    btc_target = targets["BTCUSDT"].target_usd
    eth_target = targets["ETHUSDT"].target_usd
    
    # Should be normal allocation
    assert btc_target > 0.0
    assert eth_target > 0.0
    
    # No breach metrics should be recorded (disabled)
    mock_metrics.record_position_skew_breach.assert_not_called()

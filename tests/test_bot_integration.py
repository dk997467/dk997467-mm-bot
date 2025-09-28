"""
Integration test for bot with EnhancedQuoter feature flag.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

from src.common.config import ConfigLoader
from src.common.di import AppContext
from src.strategy.market_making import MarketMakingStrategy


class TestBotIntegration:
    """Test bot integration with EnhancedQuoter."""
    
    def test_bot_creates_strategy_with_enhanced_quoting(self):
        """Test that bot creates strategy with EnhancedQuoter when feature flag is enabled."""
        # Mock config file path
        config_path = "config.yaml"
        
        # Mock ConfigLoader to return config with enhanced quoting enabled
        mock_config = Mock()
        mock_config.strategy = Mock()
        mock_config.strategy.enable_enhanced_quoting = True
        
        # Set up required strategy config values
        mock_config.strategy.vola_half_life_s = 60
        mock_config.strategy.imbalance_levels = 5
        mock_config.strategy.enable_dynamic_spread = True
        mock_config.strategy.enable_inventory_skew = True
        mock_config.strategy.enable_adverse_guard = True
        mock_config.strategy.min_spread_bps = 2
        mock_config.strategy.max_spread_bps = 25
        mock_config.strategy.k_vola_spread = 0.95
        mock_config.strategy.skew_coeff = 0.3
        mock_config.strategy.imbalance_cutoff = 0.65
        mock_config.strategy.levels_per_side = 3
        mock_config.strategy.level_spacing_coeff = 0.4
        mock_config.strategy.microprice_drift_bps = 3
        mock_config.strategy.guard_pause_ms = 300
        
        with patch('src.common.config.ConfigLoader') as mock_loader_class:
            mock_loader = Mock()
            mock_loader.load.return_value = mock_config
            mock_loader_class.return_value = mock_loader
            
            # Mock AppContext
            mock_ctx = Mock()
            mock_ctx.cfg = mock_config
            mock_ctx.metrics = Mock()
            
            # Create strategy through bot initialization path
            strategy = MarketMakingStrategy(
                config=mock_config,
                data_recorder=Mock(),
                metrics_exporter=None,
                ctx=mock_ctx
            )
            
            # Verify EnhancedQuoter was initialized
            assert strategy.enhanced_quoter is not None
            assert strategy.enhanced_quoter.ctx == mock_ctx
    
    def test_bot_creates_strategy_without_enhanced_quoting(self):
        """Test that bot creates strategy without EnhancedQuoter when feature flag is disabled."""
        # Mock config file path
        config_path = "config.yaml"
        
        # Mock ConfigLoader to return config with enhanced quoting disabled
        mock_config = Mock()
        mock_config.strategy = Mock()
        mock_config.strategy.enable_enhanced_quoting = False
        
        with patch('src.common.config.ConfigLoader') as mock_loader_class:
            mock_loader = Mock()
            mock_loader.load.return_value = mock_config
            mock_loader_class.return_value = mock_loader
            
            # Mock AppContext
            mock_ctx = Mock()
            mock_ctx.cfg = mock_config
            mock_ctx.metrics = Mock()
            
            # Create strategy through bot initialization path
            strategy = MarketMakingStrategy(
                config=mock_config,
                data_recorder=Mock(),
                metrics_exporter=None,
                ctx=mock_ctx
            )
            
            # Verify EnhancedQuoter was not initialized
            assert strategy.enhanced_quoter is None

"""
Integration tests for EnhancedQuoter feature flag integration.

Tests that:
1. Feature flag on/off switches implementation without changing external API
2. EnhancedQuoter receives AppContext and pushes quotes into the same order pipeline
3. Legacy fallback works when feature flag is disabled
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from decimal import Decimal
from typing import Dict, Any

from src.common.config import AppConfig, StrategyConfig
from src.common.di import AppContext
from src.common.models import Side, TimeInForce
from src.strategy.market_making import MarketMakingStrategy
from src.strategy.enhanced_quoting import EnhancedQuoter


class TestEnhancedQuotingIntegration:
    """Test EnhancedQuoter integration with feature flags."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create mock config with strategy section
        self.mock_config = Mock(spec=AppConfig)
        self.mock_config.strategy = Mock(spec=StrategyConfig)
        
        # Set up default strategy config values
        self.mock_config.strategy.vola_half_life_s = 60
        self.mock_config.strategy.imbalance_levels = 5
        self.mock_config.strategy.enable_dynamic_spread = True
        self.mock_config.strategy.enable_inventory_skew = True
        self.mock_config.strategy.enable_adverse_guard = True
        self.mock_config.strategy.min_spread_bps = 2
        self.mock_config.strategy.max_spread_bps = 25
        self.mock_config.strategy.k_vola_spread = 0.95
        self.mock_config.strategy.skew_coeff = 0.3
        self.mock_config.strategy.imbalance_cutoff = 0.65
        self.mock_config.strategy.levels_per_side = 3
        self.mock_config.strategy.level_spacing_coeff = 0.4
        self.mock_config.strategy.microprice_drift_bps = 3
        self.mock_config.strategy.guard_pause_ms = 300
        
        # Create mock AppContext with required attributes
        self.mock_ctx = Mock(spec=AppContext)
        self.mock_ctx.cfg = self.mock_config
        self.mock_ctx.metrics = Mock()  # Add metrics attribute
        
        # Create mock recorder and metrics
        self.mock_recorder = Mock()
        self.mock_metrics = Mock()
    
    def test_enhanced_quoting_enabled(self):
        """Test that EnhancedQuoter is used when feature flag is enabled."""
        # Enable enhanced quoting
        self.mock_config.strategy.enable_enhanced_quoting = True
        
        # Create strategy with enhanced quoting enabled
        strategy = MarketMakingStrategy(
            config=self.mock_config,
            data_recorder=self.mock_recorder,
            metrics_exporter=self.mock_metrics,
            ctx=self.mock_ctx
        )
        
        # Verify EnhancedQuoter was initialized
        assert strategy.enhanced_quoter is not None
        assert isinstance(strategy.enhanced_quoter, EnhancedQuoter)
        assert strategy.enhanced_quoter.ctx == self.mock_ctx
    
    def test_enhanced_quoting_disabled(self):
        """Test that legacy strategy is used when feature flag is disabled."""
        # Disable enhanced quoting
        self.mock_config.strategy.enable_enhanced_quoting = False
        
        # Create strategy with enhanced quoting disabled
        strategy = MarketMakingStrategy(
            config=self.mock_config,
            data_recorder=self.mock_recorder,
            metrics_exporter=self.mock_metrics,
            ctx=self.mock_ctx
        )
        
        # Verify EnhancedQuoter was not initialized
        assert strategy.enhanced_quoter is None
    
    def test_enhanced_quoting_requires_ctx(self):
        """Test that AppContext is required when enhanced quoting is enabled."""
        # Enable enhanced quoting
        self.mock_config.strategy.enable_enhanced_quoting = True
        
        # Try to create strategy without ctx - should raise ValueError
        with pytest.raises(ValueError, match="AppContext is required when enable_enhanced_quoting is True"):
            MarketMakingStrategy(
                config=self.mock_config,
                data_recorder=self.mock_recorder,
                metrics_exporter=self.mock_metrics,
                ctx=None
            )
    
    def test_strategy_state_reflects_quoting_engine(self):
        """Test that strategy state shows correct quoting engine."""
        # Test with enhanced quoting enabled
        self.mock_config.strategy.enable_enhanced_quoting = True
        strategy = MarketMakingStrategy(
            config=self.mock_config,
            data_recorder=self.mock_recorder,
            metrics_exporter=self.mock_metrics,
            ctx=self.mock_ctx
        )
        
        state = strategy.get_strategy_state()
        assert state["quoting_engine"] == "enhanced"
        
        # Test with enhanced quoting disabled
        self.mock_config.strategy.enable_enhanced_quoting = False
        strategy = MarketMakingStrategy(
            config=self.mock_config,
            data_recorder=self.mock_recorder,
            metrics_exporter=self.mock_metrics,
            ctx=self.mock_ctx
        )
        
        state = strategy.get_strategy_state()
        assert state["quoting_engine"] == "legacy"
    
    @pytest.mark.asyncio
    async def test_enhanced_quoting_orderbook_handling(self):
        """Test that EnhancedQuoter handles orderbook updates correctly."""
        # Enable enhanced quoting
        self.mock_config.strategy.enable_enhanced_quoting = True
        
        # Create strategy
        strategy = MarketMakingStrategy(
            config=self.mock_config,
            data_recorder=self.mock_recorder,
            metrics_exporter=self.mock_metrics,
            ctx=self.mock_ctx
        )
        
        # Mock quote callback
        mock_quote_callback = AsyncMock()
        strategy.set_quote_callback(mock_quote_callback)
        
        # Mock EnhancedQuoter.generate_quotes to return test quotes
        mock_quotes = [
            Mock(side="bid", size=Decimal("0.001"), price=Decimal("50000")),
            Mock(side="ask", size=Decimal("0.001"), price=Decimal("50001"))
        ]
        strategy.enhanced_quoter.generate_quotes = Mock(return_value=mock_quotes)
        
        # Test orderbook update
        test_orderbook = {
            "symbol": "BTCUSDT",
            "bids": [[50000, 1.0]],
            "asks": [[50001, 1.0]],
            "timestamp": "2025-01-01T00:00:00Z"
        }
        
        await strategy.on_orderbook_update(test_orderbook)
        
        # Verify EnhancedQuoter was called
        strategy.enhanced_quoter.generate_quotes.assert_called_once_with("BTCUSDT", test_orderbook)
        
        # Verify quote callback was called with converted quotes
        assert mock_quote_callback.call_count == 2
        
        # Check first quote (bid -> BUY)
        first_call = mock_quote_callback.call_args_list[0]
        first_quote = first_call[0][0]  # First argument of first call
        assert first_quote.side == Side.BUY
        assert first_quote.qty == Decimal("0.001")
        assert first_quote.price == Decimal("50000")
        
        # Check second quote (ask -> SELL)
        second_call = mock_quote_callback.call_args_list[1]
        second_quote = second_call[0][0]  # First argument of second call
        assert second_quote.side == Side.SELL
        assert second_quote.qty == Decimal("0.001")
        assert second_quote.price == Decimal("50001")
    
    @pytest.mark.asyncio
    async def test_legacy_orderbook_handling(self):
        """Test that legacy strategy handles orderbook updates when enhanced quoting is disabled."""
        # Disable enhanced quoting
        self.mock_config.strategy.enable_enhanced_quoting = False
        
        # Create strategy
        strategy = MarketMakingStrategy(
            config=self.mock_config,
            data_recorder=self.mock_recorder,
            metrics_exporter=self.mock_metrics,
            ctx=self.mock_ctx
        )
        
        # Mock quote callback
        mock_quote_callback = AsyncMock()
        strategy.set_quote_callback(mock_quote_callback)
        
        # Test orderbook update
        test_orderbook = {
            "symbol": "BTCUSDT",
            "bids": [[50000, 1.0]],
            "asks": [[50001, 1.0]],
            "timestamp": "2025-01-01T00:00:00Z"
        }
        
        await strategy.on_orderbook_update(test_orderbook)
        
        # Verify quote callback was not called (legacy implementation is empty)
        mock_quote_callback.assert_not_called()
    
    def test_enhanced_features_config_in_state(self):
        """Test that enhanced features configuration is reflected in strategy state."""
        # Set up mock config with enhanced features
        self.mock_config.strategy.enable_dynamic_spread = True
        self.mock_config.strategy.enable_inventory_skew = False
        self.mock_config.strategy.enable_adverse_guard = True
        
        # Create strategy
        strategy = MarketMakingStrategy(
            config=self.mock_config,
            data_recorder=self.mock_recorder,
            metrics_exporter=self.mock_metrics,
            ctx=self.mock_ctx
        )
        
        state = strategy.get_strategy_state()
        enhanced_features = state["enhanced_features"]
        
        assert enhanced_features["dynamic_spread"] is True
        assert enhanced_features["inventory_skew"] is False
        assert enhanced_features["adverse_guard"] is True
    
    @pytest.mark.asyncio
    async def test_quote_conversion_error_handling(self):
        """Test that quote conversion errors are handled gracefully."""
        # Enable enhanced quoting
        self.mock_config.strategy.enable_enhanced_quoting = True
        
        # Create strategy
        strategy = MarketMakingStrategy(
            config=self.mock_config,
            data_recorder=self.mock_recorder,
            metrics_exporter=self.mock_metrics,
            ctx=self.mock_ctx
        )
        
        # Mock quote callback
        mock_quote_callback = AsyncMock()
        strategy.set_quote_callback(mock_quote_callback)
        
        # Mock EnhancedQuoter.generate_quotes to return quote with missing required attributes
        mock_invalid_quote = Mock()
        # Remove required attributes to simulate conversion error
        del mock_invalid_quote.side
        del mock_invalid_quote.size
        del mock_invalid_quote.price
        
        strategy.enhanced_quoter.generate_quotes = Mock(return_value=[mock_invalid_quote])
        
        # Test orderbook update - should handle conversion error gracefully
        test_orderbook = {
            "symbol": "BTCUSDT",
            "bids": [[50000, 1.0]],
            "asks": [[50001, 1.0]],
            "timestamp": "2025-01-01T00:00:00Z"
        }
        
        # Should not raise exception
        await strategy.on_orderbook_update(test_orderbook)
        
        # Verify quote callback was not called due to conversion error
        mock_quote_callback.assert_not_called()
    
    def test_strategy_initialization_messages(self):
        """Test that strategy initialization prints appropriate messages."""
        # Test enhanced quoting enabled
        self.mock_config.strategy.enable_enhanced_quoting = True
        with patch('builtins.print') as mock_print:
            strategy = MarketMakingStrategy(
                config=self.mock_config,
                data_recorder=self.mock_recorder,
                metrics_exporter=self.mock_metrics,
                ctx=self.mock_ctx
            )
            mock_print.assert_called_with("EnhancedQuoter initialized")
        
        # Test enhanced quoting disabled
        self.mock_config.strategy.enable_enhanced_quoting = False
        with patch('builtins.print') as mock_print:
            strategy = MarketMakingStrategy(
                config=self.mock_config,
                data_recorder=self.mock_recorder,
                metrics_exporter=self.mock_metrics,
                ctx=self.mock_ctx
            )
            mock_print.assert_called_with("Using legacy quoting strategy")

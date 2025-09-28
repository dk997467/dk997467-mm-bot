"""
Tests for enhanced quoting logic.
"""

import pytest


def test_import_enhanced_quoting():
    """Test that enhanced quoting modules can be imported."""
    from src.strategy.enhanced_quoting import VolatilityTracker, OrderBookAnalyzer, EnhancedQuoter
    
    # Test VolatilityTracker
    tracker = VolatilityTracker(60)
    assert tracker.half_life_s == 60
    assert tracker.alpha > 0
    assert tracker.alpha < 1
    
    # Test OrderBookAnalyzer
    analyzer = OrderBookAnalyzer(5)
    assert analyzer.imbalance_levels == 5
    
    # Test EnhancedQuoter (requires mock context)
    from unittest.mock import Mock
    from src.common.di import AppContext
    
    mock_ctx = Mock(spec=AppContext)
    mock_ctx.cfg = Mock()
    mock_ctx.cfg.strategy = Mock()
    mock_ctx.cfg.strategy.vola_half_life_s = 60
    mock_ctx.cfg.strategy.imbalance_levels = 5
    mock_ctx.metrics = Mock()
    
    quoter = EnhancedQuoter(mock_ctx)
    assert quoter.vola_tracker is not None
    assert quoter.ob_analyzer is not None


def test_volatility_tracker_basic():
    """Test basic volatility tracking functionality."""
    from src.strategy.enhanced_quoting import VolatilityTracker
    
    tracker = VolatilityTracker(60)
    
    # First update should return 0 volatility
    vola = tracker.update("BTCUSDT", 50000.0)
    assert vola == 0.0
    
    # Second update with price change should return positive volatility
    vola = tracker.update("BTCUSDT", 50100.0)
    assert vola > 0.0


def test_orderbook_analyzer_basic():
    """Test basic order book analysis functionality."""
    from src.strategy.enhanced_quoting import OrderBookAnalyzer
    
    analyzer = OrderBookAnalyzer(2)
    
    # Test balanced order book
    bids = [[50000, 1.0], [49999, 1.0]]
    asks = [[50001, 1.0], [50002, 1.0]]
    
    imbalance = analyzer.compute_imbalance(bids, asks)
    assert imbalance == 0.5  # Balanced
    
    # Test microprice
    microprice, drift = analyzer.compute_microprice(bids, asks)
    assert microprice == 50000.5  # Volume-weighted average
    assert abs(drift) < 1.0  # Small drift

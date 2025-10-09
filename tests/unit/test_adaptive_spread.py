"""
Unit tests for AdaptiveSpreadEstimator.
"""

import time
import pytest
from src.common.config import AdaptiveSpreadConfig
from src.strategy.adaptive_spread import AdaptiveSpreadEstimator


def test_basic_spread_calculation():
    """Test basic spread calculation without special conditions."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        min_spread_bps=0.6,
        max_spread_bps=2.5,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Initial spread should be base spread
    spread = estimator.compute_spread_bps()
    assert spread == cfg.base_spread_bps


def test_vol_increases_spread():
    """Test that higher volatility increases spread."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        vol_sensitivity=1.0,  # Full weight
        liquidity_sensitivity=0.0,
        latency_sensitivity=0.0,
        pnl_dev_sensitivity=0.0,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Update with volatile price movements
    ts_ms = int(time.time() * 1000)
    prices = [100.0, 100.2, 100.5, 99.8, 100.3]  # High volatility
    
    for i, price in enumerate(prices):
        estimator.update_mid(price, ts_ms + i * 1000)
    
    # Spread should be higher than base
    spread = estimator.compute_spread_bps()
    assert spread > cfg.base_spread_bps


def test_low_vol_keeps_tight_spread():
    """Test that low volatility keeps spread near base."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        vol_sensitivity=1.0,
        liquidity_sensitivity=0.0,
        latency_sensitivity=0.0,
        pnl_dev_sensitivity=0.0,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Update with stable prices
    ts_ms = int(time.time() * 1000)
    prices = [100.0, 100.001, 100.002, 100.001, 100.0]  # Very low volatility
    
    for i, price in enumerate(prices):
        estimator.update_mid(price, ts_ms + i * 1000)
    
    # Spread should be close to base
    spread = estimator.compute_spread_bps()
    assert abs(spread - cfg.base_spread_bps) < 0.3


def test_low_liquidity_widens_spread():
    """Test that low liquidity widens spread."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        vol_sensitivity=0.0,
        liquidity_sensitivity=1.0,  # Full weight
        latency_sensitivity=0.0,
        pnl_dev_sensitivity=0.0,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Low liquidity should widen spread
    spread_low_liq = estimator.compute_spread_bps(
        liquidity_bid=1.0, liquidity_ask=1.0
    )
    
    # High liquidity should keep spread tight
    spread_high_liq = estimator.compute_spread_bps(
        liquidity_bid=50.0, liquidity_ask=50.0
    )
    
    assert spread_low_liq > spread_high_liq


def test_high_latency_widens_spread():
    """Test that high latency widens spread."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        vol_sensitivity=0.0,
        liquidity_sensitivity=0.0,
        latency_sensitivity=1.0,  # Full weight
        pnl_dev_sensitivity=0.0,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Add high latency samples
    for _ in range(20):
        estimator.update_latency(450.0)  # High latency
    
    spread_high_lat = estimator.compute_spread_bps()
    
    # Reset and add low latency
    estimator2 = AdaptiveSpreadEstimator(cfg)
    for _ in range(20):
        estimator2.update_latency(50.0)  # Low latency
    
    spread_low_lat = estimator2.compute_spread_bps()
    
    assert spread_high_lat > spread_low_lat


def test_pnl_drawdown_widens_spread():
    """Test that PnL drawdown widens spread."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        vol_sensitivity=0.0,
        liquidity_sensitivity=0.0,
        latency_sensitivity=0.0,
        pnl_dev_sensitivity=1.0,  # Full weight
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Simulate consistent losses (negative PnL)
    for _ in range(30):
        estimator.update_pnl(-10.0)  # Losses
    
    spread_loss = estimator.compute_spread_bps()
    
    # Reset and simulate profits
    estimator2 = AdaptiveSpreadEstimator(cfg)
    for _ in range(30):
        estimator2.update_pnl(10.0)  # Profits
    
    spread_profit = estimator2.compute_spread_bps()
    
    assert spread_loss > spread_profit


def test_clamp_to_min_spread():
    """Test that spread is clamped to min_spread_bps."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        min_spread_bps=0.8,
        max_spread_bps=2.5,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Even with all favorable conditions, spread shouldn't go below min
    spread = estimator.compute_spread_bps(
        liquidity_bid=1000.0, liquidity_ask=1000.0
    )
    
    assert spread >= cfg.min_spread_bps


def test_clamp_to_max_spread():
    """Test that spread is clamped to max_spread_bps."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        min_spread_bps=0.6,
        max_spread_bps=2.0,  # Lower max
        vol_sensitivity=1.0,
        liquidity_sensitivity=1.0,
        latency_sensitivity=1.0,
        pnl_dev_sensitivity=1.0,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Add extreme conditions
    ts_ms = int(time.time() * 1000)
    for i in range(10):
        estimator.update_mid(100.0 + i * 2, ts_ms + i * 1000)  # Volatile
        estimator.update_latency(500.0)  # High latency
        estimator.update_pnl(-100.0)  # Losses
    
    # Spread should be clamped to max
    spread = estimator.compute_spread_bps(
        liquidity_bid=0.1, liquidity_ask=0.1  # Low liquidity
    )
    
    assert spread <= cfg.max_spread_bps


def test_clamp_step_limits_change_rate():
    """Test that clamp_step_bps limits spread change per tick."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        clamp_step_bps=0.1,  # Small step
        max_spread_bps=5.0,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Get initial spread
    spread1 = estimator.compute_spread_bps()
    
    # Try to force large jump by adding extreme conditions
    estimator.vol_ema_bps = 50.0  # Manually set high vol
    spread2 = estimator.compute_spread_bps()
    
    # Change should be limited to clamp_step_bps
    delta = abs(spread2 - spread1)
    assert delta <= cfg.clamp_step_bps + 0.01  # Small tolerance


def test_cooloff_prevents_rapid_changes():
    """Test that cooloff_ms prevents rapid spread changes."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        cooloff_ms=500,  # 500ms cooloff
        clamp_step_bps=0.5,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    now_ms = int(time.time() * 1000)
    
    # First change
    spread1 = estimator.compute_spread_bps(now_ms=now_ms)
    
    # Try to change immediately (within cooloff)
    estimator.vol_ema_bps = 30.0  # Force change
    spread2 = estimator.compute_spread_bps(now_ms=now_ms + 100)
    
    # Spread should not change (in cooloff)
    assert abs(spread2 - spread1) < 0.01
    
    # After cooloff expires
    spread3 = estimator.compute_spread_bps(now_ms=now_ms + 600)
    
    # Now spread should change
    assert abs(spread3 - spread1) > 0.01


def test_disabled_returns_base_spread():
    """Test that disabled estimator returns base spread."""
    cfg = AdaptiveSpreadConfig(
        enabled=False,  # Disabled
        base_spread_bps=1.5,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Add conditions that would normally change spread
    estimator.vol_ema_bps = 50.0
    for _ in range(20):
        estimator.update_latency(500.0)
        estimator.update_pnl(-100.0)
    
    # Should always return base spread
    spread = estimator.compute_spread_bps(liquidity_bid=0.1, liquidity_ask=0.1)
    assert spread == cfg.base_spread_bps


def test_metrics_are_tracked():
    """Test that metrics are properly tracked."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    # Compute spread
    estimator.compute_spread_bps()
    
    # Check metrics
    metrics = estimator.get_metrics()
    assert 'vol_score' in metrics
    assert 'liq_score' in metrics
    assert 'lat_score' in metrics
    assert 'pnl_score' in metrics
    assert 'total_score' in metrics
    assert 'final_spread_bps' in metrics
    
    # All scores should be 0..1
    assert 0.0 <= metrics['vol_score'] <= 1.0
    assert 0.0 <= metrics['liq_score'] <= 1.0
    assert 0.0 <= metrics['lat_score'] <= 1.0
    assert 0.0 <= metrics['pnl_score'] <= 1.0

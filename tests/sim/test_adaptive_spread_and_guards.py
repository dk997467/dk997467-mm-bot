"""
E2E simulation test for AdaptiveSpread + RiskGuards.

Tests different market phases:
1. Calm: Low vol → tight spread, no guards
2. Moderate vol: Spread widens, no guards
3. Extreme: Spread max'd, HARD guard → no quoting
4. Recovery: Spread narrows, guards clear
"""

import time
import pytest
from src.common.config import AdaptiveSpreadConfig, RiskGuardsConfig
from src.strategy.adaptive_spread import AdaptiveSpreadEstimator
from src.risk.risk_guards import RiskGuards, GuardLevel


@pytest.fixture
def adaptive_spread():
    """Create adaptive spread estimator."""
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        min_spread_bps=0.6,
        max_spread_bps=2.5,
        vol_sensitivity=0.8,
        liquidity_sensitivity=0.4,
        clamp_step_bps=0.3,
    )
    return AdaptiveSpreadEstimator(cfg)


@pytest.fixture
def risk_guards():
    """Create risk guards."""
    cfg = RiskGuardsConfig(
        enabled=True,
        vol_soft_bps=12.0,
        vol_hard_bps=20.0,
        latency_p95_soft_ms=300,
        latency_p95_hard_ms=450,
        halt_ms_hard=2000,
    )
    return RiskGuards(cfg)


def test_phase_1_calm_market(adaptive_spread, risk_guards):
    """
    Phase 1: Calm market.
    - Low volatility
    - Good liquidity
    - Low latency
    Expected: Tight spread, NONE guard
    """
    ts_ms = int(time.time() * 1000)
    
    # Simulate calm market (small price movements)
    prices = [100.0, 100.001, 100.002, 100.001, 100.0]
    
    for i, price in enumerate(prices):
        adaptive_spread.update_mid(price, ts_ms + i * 1000)
        risk_guards.update_vol(price, ts_ms + i * 1000)
        
        # Low latency
        adaptive_spread.update_latency(80.0)
        risk_guards.update_latency(80.0)
    
    # Compute spread - should be tight
    spread = adaptive_spread.compute_spread_bps(
        liquidity_bid=20.0,
        liquidity_ask=20.0,
        now_ms=ts_ms + 6000
    )
    
    # Assess guards - should be NONE
    level, _ = risk_guards.assess(now_ms=ts_ms + 6000)
    
    assert spread < 1.2  # Tight spread
    assert level == GuardLevel.NONE


def test_phase_2_moderate_volatility(adaptive_spread, risk_guards):
    """
    Phase 2: Moderate volatility.
    - Moderate price swings (~8-10 bps)
    - Decent liquidity
    - Normal latency
    Expected: Wider spread, still NONE guard
    """
    ts_ms = int(time.time() * 1000)
    
    # Simulate moderate volatility
    prices = [100.0, 100.08, 100.12, 100.05, 100.15, 100.1]
    
    for i, price in enumerate(prices):
        adaptive_spread.update_mid(price, ts_ms + i * 1000)
        risk_guards.update_vol(price, ts_ms + i * 1000)
        
        # Normal latency
        adaptive_spread.update_latency(150.0)
        risk_guards.update_latency(150.0)
    
    # Compute spread - should be wider than calm
    spread = adaptive_spread.compute_spread_bps(
        liquidity_bid=15.0,
        liquidity_ask=15.0,
        now_ms=ts_ms + 7000
    )
    
    # Assess guards - should still be NONE
    level, _ = risk_guards.assess(now_ms=ts_ms + 7000)
    
    assert spread > 1.0  # Wider than base
    assert spread < 2.0  # But not max'd
    assert level == GuardLevel.NONE


def test_phase_3_extreme_conditions(adaptive_spread, risk_guards):
    """
    Phase 3: Extreme market conditions.
    - High volatility (>20 bps)
    - Low liquidity
    - High latency
    Expected: Max spread, HARD guard
    """
    ts_ms = int(time.time() * 1000)
    
    # Simulate extreme volatility
    prices = [100.0, 100.5, 101.2, 99.8, 101.5, 100.3, 102.0]
    
    for i, price in enumerate(prices):
        adaptive_spread.update_mid(price, ts_ms + i * 500)
        risk_guards.update_vol(price, ts_ms + i * 500)
        
        # High latency
        adaptive_spread.update_latency(500.0)
        risk_guards.update_latency(500.0)
        
        # Losses
        adaptive_spread.update_pnl(-50.0)
        risk_guards.update_pnl(-50.0)
    
    # Compute spread - should be at or near max
    spread = adaptive_spread.compute_spread_bps(
        liquidity_bid=1.0,  # Low liquidity
        liquidity_ask=1.0,
        now_ms=ts_ms + 4000
    )
    
    # Assess guards - should be HARD
    level, reasons = risk_guards.assess(now_ms=ts_ms + 4000)
    
    assert spread >= 2.0  # Near max
    assert level == GuardLevel.HARD
    assert len(reasons) > 0


def test_phase_4_recovery(adaptive_spread, risk_guards):
    """
    Phase 4: Market recovery.
    - Volatility normalizing
    - Liquidity returning
    - Latency improving
    Expected: Spread narrowing, guards clear
    """
    # First, create extreme conditions
    ts_ms = int(time.time() * 1000)
    extreme_prices = [100.0, 101.5, 102.0]
    
    for i, price in enumerate(extreme_prices):
        adaptive_spread.update_mid(price, ts_ms + i * 500)
        risk_guards.update_vol(price, ts_ms + i * 500)
        adaptive_spread.update_latency(500.0)
        risk_guards.update_latency(500.0)
    
    # Verify extreme state
    spread_extreme = adaptive_spread.compute_spread_bps(
        liquidity_bid=1.0, liquidity_ask=1.0, now_ms=ts_ms + 2000
    )
    level_extreme, _ = risk_guards.assess(now_ms=ts_ms + 2000)
    
    # Now simulate recovery
    ts_recovery = ts_ms + 10000
    recovery_prices = [102.0, 102.05, 102.03, 102.08, 102.06]
    
    for i, price in enumerate(recovery_prices):
        adaptive_spread.update_mid(price, ts_recovery + i * 1000)
        risk_guards.update_vol(price, ts_recovery + i * 1000)
        
        # Improving latency
        adaptive_spread.update_latency(120.0)
        risk_guards.update_latency(120.0)
        
        # Profits
        adaptive_spread.update_pnl(10.0)
        risk_guards.update_pnl(10.0)
    
    # Compute spread - should be narrowing
    spread_recovery = adaptive_spread.compute_spread_bps(
        liquidity_bid=25.0,  # Good liquidity
        liquidity_ask=25.0,
        now_ms=ts_recovery + 6000
    )
    
    # Assess guards - should clear (after halt expires)
    level_recovery, _ = risk_guards.assess(now_ms=ts_recovery + 6000)
    
    assert spread_recovery < spread_extreme  # Narrowing
    # Guard may still be HARD if in halt cooldown, so check after sufficient time
    level_final, _ = risk_guards.assess(now_ms=ts_recovery + 10000)
    assert level_final in [GuardLevel.NONE, GuardLevel.SOFT]  # Cleared or softened


def test_full_cycle_integration(adaptive_spread, risk_guards):
    """
    Full cycle: Calm → Moderate → Extreme → Recovery.
    Verify spread and guard transitions.
    """
    ts_base = int(time.time() * 1000)
    spreads = []
    guard_levels = []
    
    # Phase 1: Calm (0-5s)
    for i in range(5):
        price = 100.0 + i * 0.001
        ts = ts_base + i * 1000
        adaptive_spread.update_mid(price, ts)
        risk_guards.update_vol(price, ts)
        adaptive_spread.update_latency(80.0)
        risk_guards.update_latency(80.0)
    
    spread1 = adaptive_spread.compute_spread_bps(
        liquidity_bid=20.0, liquidity_ask=20.0, now_ms=ts_base + 5000
    )
    level1, _ = risk_guards.assess(now_ms=ts_base + 5000)
    spreads.append(spread1)
    guard_levels.append(level1)
    
    # Phase 2: Moderate (5-10s)
    for i in range(5):
        price = 100.0 + i * 0.1
        ts = ts_base + 5000 + i * 1000
        adaptive_spread.update_mid(price, ts)
        risk_guards.update_vol(price, ts)
        adaptive_spread.update_latency(200.0)
        risk_guards.update_latency(200.0)
    
    spread2 = adaptive_spread.compute_spread_bps(
        liquidity_bid=15.0, liquidity_ask=15.0, now_ms=ts_base + 10000
    )
    level2, _ = risk_guards.assess(now_ms=ts_base + 10000)
    spreads.append(spread2)
    guard_levels.append(level2)
    
    # Phase 3: Extreme (10-13s)
    for i in range(3):
        price = 100.0 + i * 0.8
        ts = ts_base + 10000 + i * 1000
        adaptive_spread.update_mid(price, ts)
        risk_guards.update_vol(price, ts)
        adaptive_spread.update_latency(550.0)
        risk_guards.update_latency(550.0)
        adaptive_spread.update_pnl(-100.0)
        risk_guards.update_pnl(-100.0)
    
    spread3 = adaptive_spread.compute_spread_bps(
        liquidity_bid=2.0, liquidity_ask=2.0, now_ms=ts_base + 13000
    )
    level3, _ = risk_guards.assess(now_ms=ts_base + 13000)
    spreads.append(spread3)
    guard_levels.append(level3)
    
    # Phase 4: Recovery (18-23s, after halt)
    for i in range(5):
        price = 102.0 + i * 0.01
        ts = ts_base + 18000 + i * 1000
        adaptive_spread.update_mid(price, ts)
        risk_guards.update_vol(price, ts)
        adaptive_spread.update_latency(100.0)
        risk_guards.update_latency(100.0)
        adaptive_spread.update_pnl(20.0)
        risk_guards.update_pnl(20.0)
    
    spread4 = adaptive_spread.compute_spread_bps(
        liquidity_bid=30.0, liquidity_ask=30.0, now_ms=ts_base + 23000
    )
    level4, _ = risk_guards.assess(now_ms=ts_base + 23000)
    spreads.append(spread4)
    guard_levels.append(level4)
    
    # Verify progression
    assert spreads[0] < spreads[1]  # Calm → Moderate (wider)
    assert spreads[1] < spreads[2]  # Moderate → Extreme (max)
    assert spreads[3] < spreads[2]  # Recovery (narrowing)
    
    assert guard_levels[0] == GuardLevel.NONE  # Calm
    assert guard_levels[1] == GuardLevel.NONE  # Moderate
    assert guard_levels[2] == GuardLevel.HARD  # Extreme
    # level4 may be NONE or SOFT depending on recovery speed


def test_no_price_crossing():
    """
    Verify that adaptive spread doesn't cause bid/ask crossing.
    """
    cfg = AdaptiveSpreadConfig(
        enabled=True,
        base_spread_bps=1.0,
        min_spread_bps=0.5,
        max_spread_bps=3.0,
    )
    estimator = AdaptiveSpreadEstimator(cfg)
    
    mid_price = 100.0
    
    # Get adaptive spread
    spread_bps = estimator.compute_spread_bps()
    
    # Apply to bid/ask
    spread_abs = mid_price * (spread_bps / 10000.0)
    bid = mid_price - spread_abs / 2
    ask = mid_price + spread_abs / 2
    
    # Verify no crossing
    assert bid < mid_price < ask
    assert (ask - bid) > 0


def test_metrics_exported_correctly():
    """
    Test that metrics from both systems are correctly exported.
    """
    spread_cfg = AdaptiveSpreadConfig(enabled=True)
    guards_cfg = RiskGuardsConfig(enabled=True)
    
    estimator = AdaptiveSpreadEstimator(spread_cfg)
    guards = RiskGuards(guards_cfg)
    
    # Update and compute
    ts_ms = int(time.time() * 1000)
    estimator.update_mid(100.0, ts_ms)
    guards.update_vol(100.0, ts_ms)
    
    estimator.compute_spread_bps()
    guards.assess()
    
    # Get metrics
    spread_metrics = estimator.get_metrics()
    guard_metrics = guards.get_metrics()
    
    # Verify keys
    assert 'final_spread_bps' in spread_metrics
    assert 'vol_score' in spread_metrics
    assert 'guard_level' in guard_metrics
    assert 'vol_bps' in guard_metrics
    
    # Verify reason counts
    reason_counts = guards.get_reason_counts()
    assert isinstance(reason_counts, dict)
    assert 'vol' in reason_counts

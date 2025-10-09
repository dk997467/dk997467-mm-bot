"""
Unit tests for RiskGuards (SOFT/HARD protection).
"""

import time
import pytest
from src.common.config import RiskGuardsConfig
from src.risk.risk_guards import RiskGuards, GuardLevel


def test_none_level_by_default():
    """Test that default state is NONE (no risk)."""
    cfg = RiskGuardsConfig(enabled=True)
    guards = RiskGuards(cfg)
    
    level, reasons = guards.assess()
    assert level == GuardLevel.NONE
    assert len(reasons) == 0


def test_vol_triggers_soft():
    """Test that moderate volatility triggers SOFT."""
    cfg = RiskGuardsConfig(
        enabled=True,
        vol_soft_bps=10.0,
        vol_hard_bps=20.0,
    )
    guards = RiskGuards(cfg)
    
    # Simulate moderate volatility
    ts_ms = int(time.time() * 1000)
    prices = [100.0, 100.15, 100.3, 100.2]  # ~12 bps moves
    
    for i, price in enumerate(prices):
        guards.update_vol(price, ts_ms + i * 1000)
    
    level, reasons = guards.assess()
    assert level == GuardLevel.SOFT
    assert any('vol:' in r for r in reasons)


def test_vol_triggers_hard():
    """Test that extreme volatility triggers HARD."""
    cfg = RiskGuardsConfig(
        enabled=True,
        vol_soft_bps=10.0,
        vol_hard_bps=20.0,
    )
    guards = RiskGuards(cfg)
    
    # Simulate extreme volatility
    ts_ms = int(time.time() * 1000)
    prices = [100.0, 100.5, 101.0, 99.5, 101.5]  # >25 bps moves
    
    for i, price in enumerate(prices):
        guards.update_vol(price, ts_ms + i * 1000)
    
    level, reasons = guards.assess()
    assert level == GuardLevel.HARD
    assert any('vol:' in r for r in reasons)


def test_latency_triggers_soft():
    """Test that high latency triggers SOFT."""
    cfg = RiskGuardsConfig(
        enabled=True,
        latency_p95_soft_ms=250,
        latency_p95_hard_ms=450,
    )
    guards = RiskGuards(cfg)
    
    # Add moderate latency samples
    for _ in range(20):
        guards.update_latency(320.0)  # Above soft, below hard
    
    level, reasons = guards.assess()
    assert level == GuardLevel.SOFT
    assert any('p95:' in r for r in reasons)


def test_latency_triggers_hard():
    """Test that extreme latency triggers HARD."""
    cfg = RiskGuardsConfig(
        enabled=True,
        latency_p95_soft_ms=250,
        latency_p95_hard_ms=450,
    )
    guards = RiskGuards(cfg)
    
    # Add extreme latency samples
    for _ in range(20):
        guards.update_latency(500.0)  # Above hard
    
    level, reasons = guards.assess()
    assert level == GuardLevel.HARD
    assert any('p95:' in r for r in reasons)


def test_pnl_drawdown_triggers_soft():
    """Test that moderate PnL drawdown triggers SOFT."""
    cfg = RiskGuardsConfig(
        enabled=True,
        pnl_soft_z=-1.5,
        pnl_hard_z=-2.5,
    )
    guards = RiskGuards(cfg)
    
    # Simulate consistent losses (z-score ~-1.8)
    for _ in range(30):
        guards.update_pnl(-15.0)  # Losses
    
    level, reasons = guards.assess()
    assert level == GuardLevel.SOFT
    assert any('pnl_z:' in r for r in reasons)


def test_pnl_drawdown_triggers_hard():
    """Test that severe PnL drawdown triggers HARD."""
    cfg = RiskGuardsConfig(
        enabled=True,
        pnl_soft_z=-1.5,
        pnl_hard_z=-2.5,
    )
    guards = RiskGuards(cfg)
    
    # Simulate severe losses (z-score < -2.5)
    for _ in range(30):
        guards.update_pnl(-50.0)  # Large losses
    
    level, reasons = guards.assess()
    assert level == GuardLevel.HARD
    assert any('pnl_z:' in r for r in reasons)


def test_inventory_triggers_soft():
    """Test that moderate inventory triggers SOFT."""
    cfg = RiskGuardsConfig(
        enabled=True,
        inventory_pct_soft=6.0,
        inventory_pct_hard=10.0,
    )
    guards = RiskGuards(cfg)
    
    # Set moderate inventory
    guards.update_inventory_pct(7.5)  # Above soft, below hard
    
    level, reasons = guards.assess()
    assert level == GuardLevel.SOFT
    assert any('inv:' in r for r in reasons)


def test_inventory_triggers_hard():
    """Test that extreme inventory triggers HARD."""
    cfg = RiskGuardsConfig(
        enabled=True,
        inventory_pct_soft=6.0,
        inventory_pct_hard=10.0,
    )
    guards = RiskGuards(cfg)
    
    # Set extreme inventory
    guards.update_inventory_pct(11.5)  # Above hard
    
    level, reasons = guards.assess()
    assert level == GuardLevel.HARD
    assert any('inv:' in r for r in reasons)


def test_negative_inventory_triggers():
    """Test that negative inventory also triggers guards."""
    cfg = RiskGuardsConfig(
        enabled=True,
        inventory_pct_soft=6.0,
        inventory_pct_hard=10.0,
    )
    guards = RiskGuards(cfg)
    
    # Set large negative inventory
    guards.update_inventory_pct(-11.5)  # abs > hard
    
    level, reasons = guards.assess()
    assert level == GuardLevel.HARD
    assert any('inv:' in r for r in reasons)


def test_taker_fills_trigger_soft():
    """Test that excessive taker fills trigger SOFT."""
    cfg = RiskGuardsConfig(
        enabled=True,
        taker_fills_window_min=15,
        taker_fills_soft=12,
        taker_fills_hard=20,
    )
    guards = RiskGuards(cfg)
    
    # Add taker fills
    now_ms = int(time.time() * 1000)
    for i in range(15):  # 15 fills (above soft)
        guards.update_taker_fills(now_ms + i * 1000)
    
    level, reasons = guards.assess(now_ms=now_ms + 16000)
    assert level == GuardLevel.SOFT
    assert any('takers:' in r for r in reasons)


def test_taker_fills_trigger_hard():
    """Test that extreme taker fills trigger HARD."""
    cfg = RiskGuardsConfig(
        enabled=True,
        taker_fills_window_min=15,
        taker_fills_soft=12,
        taker_fills_hard=20,
    )
    guards = RiskGuards(cfg)
    
    # Add many taker fills
    now_ms = int(time.time() * 1000)
    for i in range(25):  # 25 fills (above hard)
        guards.update_taker_fills(now_ms + i * 1000)
    
    level, reasons = guards.assess(now_ms=now_ms + 26000)
    assert level == GuardLevel.HARD
    assert any('takers:' in r for r in reasons)


def test_hard_halt_period():
    """Test that HARD guard sets halt period."""
    cfg = RiskGuardsConfig(
        enabled=True,
        vol_hard_bps=15.0,
        halt_ms_hard=2000,
    )
    guards = RiskGuards(cfg)
    
    # Trigger HARD
    ts_ms = int(time.time() * 1000)
    guards.vol_ema_bps = 30.0  # Force high vol
    
    level1, _ = guards.assess(now_ms=ts_ms)
    assert level1 == GuardLevel.HARD
    
    # Check that halt period is active
    level2, reasons = guards.assess(now_ms=ts_ms + 500)
    assert level2 == GuardLevel.HARD
    assert 'halt_cooldown' in reasons
    
    # After halt expires
    level3, _ = guards.assess(now_ms=ts_ms + 2500)
    # Should re-assess (vol still high, so still HARD)
    assert level3 == GuardLevel.HARD


def test_multiple_triggers_choose_hard():
    """Test that multiple triggers choose HARD if any qualifies."""
    cfg = RiskGuardsConfig(
        enabled=True,
        vol_soft_bps=10.0,
        vol_hard_bps=20.0,
        latency_p95_soft_ms=250,
        latency_p95_hard_ms=450,
    )
    guards = RiskGuards(cfg)
    
    # Vol: SOFT level
    ts_ms = int(time.time() * 1000)
    guards.vol_ema_bps = 12.0
    
    # Latency: HARD level
    for _ in range(20):
        guards.update_latency(500.0)
    
    level, reasons = guards.assess()
    assert level == GuardLevel.HARD  # Highest level wins
    assert len(reasons) >= 1


def test_disabled_returns_none():
    """Test that disabled guards always return NONE."""
    cfg = RiskGuardsConfig(
        enabled=False,  # Disabled
    )
    guards = RiskGuards(cfg)
    
    # Add extreme conditions
    guards.vol_ema_bps = 100.0
    guards.update_inventory_pct(50.0)
    for _ in range(20):
        guards.update_latency(1000.0)
        guards.update_pnl(-1000.0)
    
    level, reasons = guards.assess()
    assert level == GuardLevel.NONE
    assert len(reasons) == 0


def test_metrics_are_tracked():
    """Test that metrics are properly tracked."""
    cfg = RiskGuardsConfig(enabled=True)
    guards = RiskGuards(cfg)
    
    # Update some metrics
    ts_ms = int(time.time() * 1000)
    guards.update_vol(100.0, ts_ms)
    guards.update_latency(150.0)
    guards.update_pnl(5.0)
    guards.update_inventory_pct(3.0)
    
    # Assess
    guards.assess()
    
    # Get metrics
    metrics = guards.get_metrics()
    assert 'vol_bps' in metrics
    assert 'latency_p95_ms' in metrics
    assert 'pnl_z_score' in metrics
    assert 'inventory_pct' in metrics
    assert 'guard_level' in metrics
    
    # Check reason counts
    reason_counts = guards.get_reason_counts()
    assert 'vol' in reason_counts
    assert 'latency' in reason_counts
    assert 'pnl' in reason_counts
    assert 'inventory' in reason_counts
    assert 'takers' in reason_counts


def test_old_taker_fills_expire():
    """Test that old taker fills outside window are ignored."""
    cfg = RiskGuardsConfig(
        enabled=True,
        taker_fills_window_min=1,  # 1 minute window
        taker_fills_soft=5,
        taker_fills_hard=10,
    )
    guards = RiskGuards(cfg)
    
    # Add fills in the past (outside window)
    old_ts = int(time.time() * 1000) - (120 * 1000)  # 2 minutes ago
    for i in range(20):
        guards.update_taker_fills(old_ts + i * 1000)
    
    # Assess now - old fills should be ignored
    now_ms = int(time.time() * 1000)
    level, _ = guards.assess(now_ms=now_ms)
    assert level == GuardLevel.NONE  # No recent fills

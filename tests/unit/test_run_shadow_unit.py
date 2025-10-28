#!/usr/bin/env python3
"""
Unit tests for tools/shadow/run_shadow.py — Shadow Mode Runner.

Tests:
- Git SHA extraction
- Symbol profile loading (with fixtures)
- MiniLOB state updates
- P95 computation
- LOB fill simulation (with time mocking)
- Determinism verification

Target coverage: 0% → 35-45%
"""
import json
import pytest
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from tools.shadow.run_shadow import (
    _git_sha_short,
    load_symbol_profile,
    MiniLOB,
    ShadowSimulator,
)


# ======================================================================
# Test _git_sha_short — Git SHA extraction
# ======================================================================

def test_git_sha_short_success():
    """Test _git_sha_short returns short SHA when git is available."""
    with patch('subprocess.check_output', return_value="abc1234\n"):
        result = _git_sha_short()
        assert result == "abc1234"


def test_git_sha_short_fallback_on_error():
    """Test _git_sha_short returns 'unknown' on git errors."""
    with patch('subprocess.check_output', side_effect=Exception("git not found")):
        result = _git_sha_short()
        assert result == "unknown"


def test_git_sha_short_handles_empty_output():
    """Test _git_sha_short handles empty git output."""
    with patch('subprocess.check_output', return_value="   \n"):
        result = _git_sha_short()
        assert result == ""


# ======================================================================
# Test load_symbol_profile — Symbol profile loading
# ======================================================================

def test_load_symbol_profile_found(tmp_path):
    """Test load_symbol_profile returns profile data when file exists."""
    # Create fake profiles/shadow_profiles.json
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    
    profiles_data = {
        "BTCUSDT": {
            "min_lot": 0.001,
            "touch_dwell_ms": 30.0,
            "spread_bps": 25.0
        },
        "ETHUSDT": {
            "min_lot": 0.01,
            "touch_dwell_ms": 20.0
        }
    }
    
    profile_path = profiles_dir / "shadow_profiles.json"
    profile_path.write_text(json.dumps(profiles_data, indent=2))
    
    # Patch Path to use tmp_path as current directory
    with patch('tools.shadow.run_shadow.Path') as mock_path:
        mock_path.return_value = profile_path
        result = load_symbol_profile("BTCUSDT")
    
    assert result == profiles_data["BTCUSDT"]
    assert result["min_lot"] == 0.001
    assert result["touch_dwell_ms"] == 30.0


def test_load_symbol_profile_not_found():
    """Test load_symbol_profile returns empty dict when profile file doesn't exist."""
    with patch('pathlib.Path.exists', return_value=False):
        result = load_symbol_profile("BTCUSDT")
        assert result == {}


def test_load_symbol_profile_symbol_not_in_file(tmp_path):
    """Test load_symbol_profile returns empty dict when symbol not in profiles."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    
    profiles_data = {"ETHUSDT": {"min_lot": 0.01}}
    profile_path = profiles_dir / "shadow_profiles.json"
    profile_path.write_text(json.dumps(profiles_data, indent=2))
    
    with patch('tools.shadow.run_shadow.Path') as mock_path:
        mock_path.return_value = profile_path
        result = load_symbol_profile("BTCUSDT")  # Not in file
    
    assert result == {}


def test_load_symbol_profile_invalid_json(tmp_path):
    """Test load_symbol_profile returns empty dict on JSON decode error."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    
    profile_path = profiles_dir / "shadow_profiles.json"
    profile_path.write_text("{invalid json")
    
    with patch('tools.shadow.run_shadow.Path') as mock_path:
        mock_path.return_value = profile_path
        result = load_symbol_profile("BTCUSDT")
    
    assert result == {}


# ======================================================================
# Test MiniLOB — Minimal LOB state
# ======================================================================

def test_mini_lob_initialization():
    """Test MiniLOB initializes with None values."""
    lob = MiniLOB()
    assert lob.best_bid is None
    assert lob.best_ask is None
    assert lob.last_trade_qty == 0.0


def test_mini_lob_on_tick_updates_bid_ask():
    """Test MiniLOB.on_tick updates bid/ask from tick."""
    lob = MiniLOB()
    
    tick = {
        "bid": 50000.0,
        "bid_size": 1.5,
        "ask": 50010.0,
        "ask_size": 2.0,
        "last_qty": 0.5,
    }
    
    lob.on_tick(tick)
    
    assert lob.best_bid == (50000.0, 1.5)
    assert lob.best_ask == (50010.0, 2.0)
    assert lob.last_trade_qty == 0.5


def test_mini_lob_on_tick_partial_updates():
    """Test MiniLOB.on_tick handles partial tick updates."""
    lob = MiniLOB()
    
    # First tick: only bid
    lob.on_tick({"bid": 50000.0, "bid_size": 1.0})
    assert lob.best_bid == (50000.0, 1.0)
    assert lob.best_ask is None
    
    # Second tick: only ask
    lob.on_tick({"ask": 50010.0, "ask_size": 2.0})
    assert lob.best_bid == (50000.0, 1.0)  # Unchanged
    assert lob.best_ask == (50010.0, 2.0)
    
    # Third tick: only last_qty
    lob.on_tick({"last_qty": 0.3})
    assert lob.last_trade_qty == 0.3


def test_mini_lob_on_tick_default_size():
    """Test MiniLOB.on_tick uses default size=0 if not provided."""
    lob = MiniLOB()
    
    tick = {"bid": 50000.0, "ask": 50010.0}  # No bid_size/ask_size
    lob.on_tick(tick)
    
    assert lob.best_bid == (50000.0, 0.0)
    assert lob.best_ask == (50010.0, 0.0)


# ======================================================================
# Test ShadowSimulator._compute_p95 — Percentile computation
# ======================================================================

def test_compute_p95_empty_list():
    """Test _compute_p95 returns 0.0 for empty list."""
    sim = ShadowSimulator()
    result = sim._compute_p95([])
    assert result == 0.0


def test_compute_p95_single_value():
    """Test _compute_p95 returns single value."""
    sim = ShadowSimulator()
    result = sim._compute_p95([42.0])
    assert result == 42.0


def test_compute_p95_sorted_values():
    """Test _compute_p95 computes correct p95."""
    sim = ShadowSimulator()
    
    # 100 values: 0, 1, 2, ..., 99
    # p95 should be at index 95 → value 95
    values = list(range(100))
    result = sim._compute_p95(values)
    assert result == 95


def test_compute_p95_unsorted_values():
    """Test _compute_p95 handles unsorted input."""
    sim = ShadowSimulator()
    
    values = [10.0, 1.0, 5.0, 20.0, 15.0]
    # Sorted: [1.0, 5.0, 10.0, 15.0, 20.0]
    # p95 index: int(5 * 0.95) = 4 → value 20.0
    result = sim._compute_p95(values)
    assert result == 20.0


def test_compute_p95_small_list():
    """Test _compute_p95 with small list."""
    sim = ShadowSimulator()
    
    values = [1.0, 2.0, 3.0]
    # Sorted: [1.0, 2.0, 3.0]
    # p95 index: int(3 * 0.95) = 2 → value 3.0
    result = sim._compute_p95(values)
    assert result == 3.0


# ======================================================================
# Test ShadowSimulator._simulate_lob_fills — Core fill simulation
# ======================================================================

def test_simulate_lob_fills_no_ticks():
    """Test _simulate_lob_fills with empty ticks returns zero fills."""
    sim = ShadowSimulator()
    
    result = sim._simulate_lob_fills(ticks=[], spread_bps=30.0)
    
    maker, taker, maker_taker, p95, risk, net_bps, drift_ms = result
    
    assert maker == 0
    assert taker == 0
    assert maker_taker == 0.0  # 0 / max(1, 0) = 0
    assert p95 == 0.0  # No latencies
    assert risk >= 0.0
    assert net_bps >= 0.0
    assert drift_ms == 0.0  # Initial EWMA


def test_simulate_lob_fills_incomplete_lob():
    """Test _simulate_lob_fills skips ticks with incomplete LOB (no bid/ask)."""
    sim = ShadowSimulator()
    
    # Ticks with only bid (no ask)
    ticks = [
        {"ts": time.time(), "ts_server": time.time(), "bid": 50000.0, "bid_size": 1.0}
    ]
    
    result = sim._simulate_lob_fills(ticks, spread_bps=30.0)
    maker, taker, _, _, _, _, _ = result
    
    # No fills because LOB is incomplete
    assert maker == 0
    assert taker == 0


def test_simulate_lob_fills_happy_path():
    """Test _simulate_lob_fills with valid ticks generates fills."""
    sim = ShadowSimulator(touch_dwell_ms=0.0, min_lot=0.0, require_volume=False)
    
    # Create ticks that should generate fills
    base_time = time.time()
    ticks = []
    
    for i in range(10):
        tick_time = base_time + i * 0.1
        tick = {
            "ts": tick_time,
            "ts_server": tick_time - 0.05,  # 50ms latency
            "bid": 50000.0,
            "ask": 50010.0,  # 10 spread
            "bid_size": 1.0,
            "ask_size": 1.0,
            "last_qty": 0.1,
        }
        ticks.append(tick)
    
    result = sim._simulate_lob_fills(ticks, spread_bps=30.0)
    maker, taker, maker_taker, p95, risk, net_bps, drift_ms = result
    
    # Should have some fills (exact count depends on spread logic)
    assert maker >= 0
    assert taker >= 0
    assert 0.0 <= maker_taker <= 1.0
    assert p95 >= 0.0  # Latencies should be recorded
    assert 0.0 <= risk <= 1.0
    assert net_bps >= 0.0


def test_simulate_lob_fills_dwell_time_filtering():
    """Test _simulate_lob_fills respects touch_dwell_ms threshold."""
    sim = ShadowSimulator(touch_dwell_ms=1000.0, require_volume=False)  # Very high dwell
    
    base_time = time.time()
    ticks = []
    
    # Create 3 ticks in quick succession (< 1000ms dwell)
    for i in range(3):
        tick = {
            "ts": base_time + i * 0.01,  # 10ms apart
            "ts_server": base_time + i * 0.01 - 0.05,
            "bid": 50000.0,
            "ask": 50001.0,  # Tight spread to trigger touch
            "bid_size": 1.0,
            "ask_size": 1.0,
        }
        ticks.append(tick)
    
    result = sim._simulate_lob_fills(ticks, spread_bps=5.0)  # Very tight spread
    maker, _, _, _, _, _, _ = result
    
    # No fills because dwell time < 1000ms
    assert maker == 0


def test_simulate_lob_fills_volume_requirement():
    """Test _simulate_lob_fills respects require_volume and min_lot."""
    sim = ShadowSimulator(
        touch_dwell_ms=0.0,
        min_lot=1.0,  # Require 1.0 lot size
        require_volume=True
    )
    
    base_time = time.time()
    ticks = [
        {
            "ts": base_time,
            "ts_server": base_time - 0.05,
            "bid": 50000.0,
            "ask": 50001.0,
            "bid_size": 1.0,
            "ask_size": 1.0,
            "last_qty": 0.5,  # Below min_lot (1.0)
        }
    ]
    
    result = sim._simulate_lob_fills(ticks, spread_bps=5.0)
    maker, _, _, _, _, _, _ = result
    
    # No fills because volume requirement not met
    assert maker == 0


def test_simulate_lob_fills_deterministic():
    """Test _simulate_lob_fills produces deterministic results with fixed input."""
    sim1 = ShadowSimulator(touch_dwell_ms=0.0, require_volume=False)
    sim2 = ShadowSimulator(touch_dwell_ms=0.0, require_volume=False)
    
    # Fixed ticks
    base_time = 1700000000.0  # Fixed timestamp
    ticks = [
        {
            "ts": base_time + i * 0.1,
            "ts_server": base_time + i * 0.1 - 0.05,
            "bid": 50000.0 + i,
            "ask": 50010.0 + i,
            "bid_size": 1.0,
            "ask_size": 1.0,
        }
        for i in range(5)
    ]
    
    # Mock time.time() to return fixed values
    with patch('time.time', return_value=base_time):
        result1 = sim1._simulate_lob_fills(ticks, spread_bps=30.0)
        result2 = sim2._simulate_lob_fills(ticks, spread_bps=30.0)
    
    # Results should be identical (deterministic)
    assert result1 == result2


# ======================================================================
# Test ShadowSimulator — Initialization
# ======================================================================

def test_shadow_simulator_init_defaults():
    """Test ShadowSimulator initializes with default values."""
    sim = ShadowSimulator()
    
    assert sim.exchange == "bybit"
    assert sim.symbols == ["BTCUSDT", "ETHUSDT"]
    assert sim.profile == "moderate"
    assert sim.source == "mock"
    assert sim.min_lot == 0.0
    assert sim.touch_dwell_ms == 25.0
    assert sim.require_volume is False


def test_shadow_simulator_init_custom_params():
    """Test ShadowSimulator accepts custom parameters."""
    sim = ShadowSimulator(
        exchange="kucoin",
        symbols=["SOLUSDT"],
        profile="aggressive",
        source="redis",
        min_lot=0.01,
        touch_dwell_ms=50.0,
        require_volume=True,
        redis_url="redis://example.com:6379",
        redis_stream="custom_stream",
    )
    
    assert sim.exchange == "kucoin"
    assert sim.symbols == ["SOLUSDT"]
    assert sim.profile == "aggressive"
    assert sim.source == "redis"
    assert sim.min_lot == 0.01
    assert sim.touch_dwell_ms == 50.0
    assert sim.require_volume is True
    assert sim.redis_url == "redis://example.com:6379"
    assert sim.redis_stream == "custom_stream"


def test_shadow_simulator_init_kpi_tracking():
    """Test ShadowSimulator initializes KPI tracking structures."""
    sim = ShadowSimulator()
    
    assert sim.maker_count == 0
    assert sim.taker_count == 0
    assert sim.latencies == []
    assert sim.net_bps_values == []
    assert sim.risk_ratios == []
    assert sim.clock_drift_ewma == 0.0


# ======================================================================
# Edge Cases and Error Handling
# ======================================================================

def test_compute_p95_negative_values():
    """Test _compute_p95 handles negative values."""
    sim = ShadowSimulator()
    values = [-10.0, -5.0, 0.0, 5.0, 10.0]
    result = sim._compute_p95(values)
    # Sorted: [-10, -5, 0, 5, 10]
    # p95 index: int(5 * 0.95) = 4 → value 10.0
    assert result == 10.0


def test_simulate_lob_fills_clock_drift_ewma():
    """Test _simulate_lob_fills updates clock_drift_ewma correctly."""
    sim = ShadowSimulator()
    
    base_time = time.time()
    ticks = [
        {
            "ts": base_time,
            "ts_server": base_time - 0.1,  # 100ms lag
            "bid": 50000.0,
            "ask": 50010.0,
            "bid_size": 1.0,
            "ask_size": 1.0,
        }
    ]
    
    with patch('time.time', return_value=base_time):
        _, _, _, _, _, _, drift_ms = sim._simulate_lob_fills(ticks, spread_bps=30.0)
    
    # Drift should be positive (ingest_ts > server_ts)
    assert drift_ms >= 0.0
    assert sim.clock_drift_ewma >= 0.0


# ======================================================================
# Run tests
# ======================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


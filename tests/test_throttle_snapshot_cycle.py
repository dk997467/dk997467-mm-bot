"""
Throttle snapshot cycle test: save -> load -> equivalence across restart.
"""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from src.guards.throttle import ThrottleGuard
from src.common.config import ThrottleConfig


def test_throttle_snapshot_cycle_equivalence():
    cfg = ThrottleConfig(window_sec=10.0, max_creates_per_sec=5.0, max_amends_per_sec=10.0, max_cancels_per_sec=20.0, per_symbol=True)
    tg = ThrottleGuard(cfg)

    # Simulate some events
    now = 1000.0
    for i in range(3):
        tg.on_event('create', 'BTCUSDT', now + i * 0.1)
    for i in range(2):
        tg.on_event('cancel', 'ETHUSDT', now + i * 0.2)

    snap = tg.to_snapshot()

    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir) / "throttle.json"
        p.write_text(json.dumps(snap, sort_keys=True, separators=(",", ":")), encoding='utf-8')

        # New guard, load snapshot
        tg2 = ThrottleGuard(cfg)
        data = json.loads(p.read_text(encoding='utf-8'))
        tg2.load_snapshot(data)

        snap2 = tg2.to_snapshot()

        # Basic equivalence on key fields
        assert snap2["version"] == 2
        assert "window_sec" in snap2
        assert "symbols" in snap2
        assert snap2["window_sec"] == snap["window_sec"]
        
        # Check that symbols are preserved
        assert "BTCUSDT" in snap2["symbols"]
        assert "ETHUSDT" in snap2["symbols"]


# Test throttle snapshot v2 save/load cycle and legacy format compatibility
from types import SimpleNamespace


def test_throttle_snapshot_cycle():
    from src.guards.throttle import ThrottleGuard, _Ring
    from src.common.config import ThrottleConfig

    # Test per-symbol throttle guard
    cfg = ThrottleConfig(
        window_sec=3,
        per_symbol=True,
        max_creates_per_sec=10,
        max_amends_per_sec=20,
        max_cancels_per_sec=30,
        error_rate_trigger=0.1,
        ws_lag_trigger_ms=100,
        backoff_base_ms=100,
        backoff_max_ms=5000
    )
    
    guard = ThrottleGuard(cfg)
    
    # Add some events to create state
    ts = 1000
    guard.on_event("create", "BTCUSDT", ts)
    guard.on_event("create", "BTCUSDT", ts)
    guard.on_event("amend", "BTCUSDT", ts)
    
    ts += 1
    guard.on_event("cancel", "BTCUSDT", ts)
    guard.on_event("create", "ETHUSDT", ts)
    
    # Create snapshot v2
    snap = guard.to_snapshot()
    
    # Verify v2 format
    assert snap["version"] == 2
    assert snap["window_sec"] == 3
    assert "symbols" in snap
    assert "BTCUSDT" in snap["symbols"]
    assert "ETHUSDT" in snap["symbols"]
    
    # Check BTCUSDT ring buffer state
    btc_data = snap["symbols"]["BTCUSDT"]
    assert "create" in btc_data
    assert "amend" in btc_data
    assert "cancel" in btc_data
    
    create_data = btc_data["create"]
    assert "base_ts" in create_data
    assert "idx" in create_data
    assert "ring" in create_data
    assert len(create_data["ring"]) == 3  # window_sec
    
    # Test load snapshot v2
    guard2 = ThrottleGuard(cfg)
    guard2.load_snapshot(snap)
    
    # Verify state is restored
    counts1 = guard.get_window_counts("BTCUSDT", ts)
    counts2 = guard2.get_window_counts("BTCUSDT", ts)
    assert counts1 == counts2
    
    # Test global windows format
    cfg_global = ThrottleConfig(
        window_sec=2,
        per_symbol=False,
        max_creates_per_sec=10,
        max_amends_per_sec=20,
        max_cancels_per_sec=30,
        error_rate_trigger=0.1,
        ws_lag_trigger_ms=100,
        backoff_base_ms=100,
        backoff_max_ms=5000
    )
    
    guard_global = ThrottleGuard(cfg_global)
    
    # Add events
    ts = 1000
    guard_global.on_event("create", "ANY", ts)
    guard_global.on_event("amend", "ANY", ts)
    
    # Create snapshot
    snap_global = guard_global.to_snapshot()
    
    # Verify global format 
    assert snap_global["version"] == 2
    assert snap_global["window_sec"] == 2
    # For per_symbol=False, should still use symbols format
    assert "symbols" in snap_global
    
    # Test legacy v1 format compatibility
    legacy_snap = {
        "version": 1,
        "window_since": "2023-01-01T00:00:00+00:00",
        "events_total": 42,
        "backoff_ms_max": 1000,
        "last_event_ts": "2023-01-01T00:01:00+00:00"
    }
    
    guard_legacy = ThrottleGuard(cfg)
    guard_legacy.load_snapshot(legacy_snap)
    
    # Legacy format should be loaded into snapshot meta fields
    assert guard_legacy._snapshot_events_total == 42
    assert guard_legacy._last_backoff_ms_max == 1000.0
    
    # Legacy format should not affect ring buffer state
    counts_legacy = guard_legacy.get_window_counts("BTCUSDT", ts)
    assert counts_legacy["create"] == 0  # No events in ring buffer
    assert counts_legacy["amend"] == 0
    assert counts_legacy["cancel"] == 0
    
    # Test reset functionality
    guard.reset()
    
    # All ring buffers should be zeroed
    counts_reset = guard.get_window_counts("BTCUSDT", ts)
    assert counts_reset["create"] == 0
    assert counts_reset["amend"] == 0
    assert counts_reset["cancel"] == 0
    
    # Ring buffer size should remain constant 
    guard._ensure_symbol("BTCUSDT")
    assert len(guard._rings["BTCUSDT"]["create"].ring) == 3



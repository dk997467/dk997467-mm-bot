#!/usr/bin/env python3
"""
Unit tests for guards module - lightweight sanity checks.

Tests Debounce and PartialFreezeState functionality.
"""

import pytest
import time


@pytest.mark.smoke
def test_debounce_open():
    """Test Debounce opens after open_ms duration."""
    from tools.soak.guards import Debounce
    
    debounce = Debounce(open_ms=100, close_ms=200)  # Fast for testing
    
    # Signal TRUE but not long enough
    debounce.update(True)
    assert not debounce.is_active(), "Should not activate immediately"
    
    # Wait and signal again
    time.sleep(0.11)  # 110ms
    changed = debounce.update(True)
    
    assert changed, "Should report state change"
    assert debounce.is_active(), "Should be active after open_ms"


@pytest.mark.smoke
def test_debounce_close():
    """Test Debounce closes after close_ms duration."""
    from tools.soak.guards import Debounce
    
    debounce = Debounce(open_ms=100, close_ms=200)
    
    # Activate
    time.sleep(0.11)
    debounce.update(True)
    assert debounce.is_active()
    
    # Signal FALSE but not long enough
    debounce.update(False)
    assert debounce.is_active(), "Should not deactivate immediately"
    
    # Wait and signal again
    time.sleep(0.21)  # 210ms
    changed = debounce.update(False)
    
    assert changed, "Should report state change"
    assert not debounce.is_active(), "Should be inactive after close_ms"


@pytest.mark.smoke
def test_partial_freeze_subsystems():
    """Test PartialFreezeState freezes correct subsystems."""
    from tools.soak.guards import PartialFreezeState
    
    freeze = PartialFreezeState()
    
    # Not frozen initially
    assert not freeze.is_any_frozen()
    assert not freeze.is_frozen('rebid')
    
    # Activate freeze
    freeze.activate(subsystems=['rebid', 'rescue_taker'], reason='oscillation')
    
    assert freeze.is_any_frozen()
    assert freeze.is_frozen('rebid'), "rebid should be frozen"
    assert freeze.is_frozen('rescue_taker'), "rescue_taker should be frozen"
    assert not freeze.is_frozen('edge'), "edge should NEVER be frozen"


@pytest.mark.smoke
def test_partial_freeze_min_duration():
    """Test PartialFreezeState respects min freeze duration."""
    from tools.soak.guards import PartialFreezeState
    
    freeze = PartialFreezeState()
    freeze.min_freeze_duration_ms = 100  # Fast for testing
    
    freeze.activate(subsystems=['rebid'], reason='test')
    
    # Try to deactivate immediately
    success = freeze.deactivate()
    assert not success, "Should not deactivate before min duration"
    assert freeze.is_any_frozen()
    
    # Wait and try again
    time.sleep(0.11)  # 110ms
    success = freeze.deactivate()
    assert success, "Should deactivate after min duration"
    assert not freeze.is_any_frozen()


@pytest.mark.smoke
def test_partial_freeze_status():
    """Test PartialFreezeState get_status method."""
    from tools.soak.guards import PartialFreezeState
    
    freeze = PartialFreezeState()
    
    # Inactive status
    status = freeze.get_status()
    assert not status['active']
    assert status['subsystems'] == []
    
    # Active status
    freeze.activate(subsystems=['rebid', 'rescue_taker'], reason='oscillation')
    status = freeze.get_status()
    
    assert status['active']
    assert 'rebid' in status['subsystems']
    assert 'rescue_taker' in status['subsystems']
    assert status['reason'] == 'oscillation'
    assert 'elapsed_ms' in status


@pytest.mark.smoke
def test_apply_partial_freeze():
    """Test apply_partial_freeze filters deltas correctly."""
    from tools.soak.guards import PartialFreezeState, apply_partial_freeze
    
    freeze = PartialFreezeState()
    
    proposed_deltas = {
        'base_spread_bps_delta': 0.01,      # rebid subsystem
        'replace_rate_per_min': 0.95,       # rebid subsystem
        'rescue_max_ratio': 0.05,           # rescue_taker subsystem
        'impact_cap_ratio': 0.10,           # edge subsystem
        'tail_age_ms': 50,                  # edge subsystem
    }
    
    # No freeze - all deltas pass through
    filtered = apply_partial_freeze(proposed_deltas, freeze)
    assert len(filtered) == len(proposed_deltas)
    
    # Freeze rebid and rescue_taker
    freeze.activate(subsystems=['rebid', 'rescue_taker'], reason='test')
    
    filtered = apply_partial_freeze(proposed_deltas, freeze)
    
    # Only edge deltas should remain
    assert 'base_spread_bps_delta' not in filtered, "rebid delta should be filtered"
    assert 'replace_rate_per_min' not in filtered, "rebid delta should be filtered"
    assert 'rescue_max_ratio' not in filtered, "rescue delta should be filtered"
    assert 'impact_cap_ratio' in filtered, "edge delta should pass"
    assert 'tail_age_ms' in filtered, "edge delta should pass"


#!/usr/bin/env python3
"""
Guard logic for soak auto-tuning: partial freeze, debounce, hysteresis.

Implements:
  - Debounce class with hysteresis (open >= 2500ms, close >= 4000ms)
  - Partial freeze (subsystem-level: rebid, rescue_taker)
  - Total freeze (backward compatibility)
"""

import time
from typing import Dict, Any, List, Optional


class Debounce:
    """
    Debounce/hysteresis for guard state transitions.
    
    Prevents rapid oscillation by requiring state to persist for minimum duration.
    
    Args:
        open_ms: Minimum time (ms) signal must be TRUE to open (default: 2500ms)
        close_ms: Minimum time (ms) signal must be FALSE to close (default: 4000ms)
    
    Usage:
        debounce = Debounce(open_ms=2500, close_ms=4000)
        
        # Called each iteration with current signal
        if debounce.update(signal=True):
            print("Guard activated (debounced)")
        
        if debounce.is_active():
            print("Guard still active")
    """
    
    def __init__(self, open_ms: float = 2500, close_ms: float = 4000):
        self.open_ms = open_ms
        self.close_ms = close_ms
        
        self._state = False
        self._signal_start_ms: Optional[float] = None
        self._last_update_ms = time.time() * 1000
    
    def update(self, signal: bool) -> bool:
        """
        Update debounce with new signal value.
        
        Args:
            signal: Current signal state (True/False)
        
        Returns:
            True if state changed this update
        """
        now_ms = time.time() * 1000
        
        # If signal changed, reset timer
        if signal != self._prev_signal():
            self._signal_start_ms = now_ms
        
        # Check if signal persisted long enough
        elapsed_ms = now_ms - (self._signal_start_ms or now_ms)
        
        old_state = self._state
        
        if signal and not self._state:
            # Opening: need signal TRUE for open_ms
            if elapsed_ms >= self.open_ms:
                self._state = True
        
        elif not signal and self._state:
            # Closing: need signal FALSE for close_ms
            if elapsed_ms >= self.close_ms:
                self._state = False
        
        self._last_update_ms = now_ms
        
        # Return True if state changed
        return self._state != old_state
    
    def is_active(self) -> bool:
        """Check if guard is currently active (debounced state)."""
        return self._state
    
    def reset(self):
        """Reset debounce to initial state."""
        self._state = False
        self._signal_start_ms = None
    
    def _prev_signal(self) -> bool:
        """Infer previous signal from current state."""
        return self._state


class PartialFreezeState:
    """
    Partial freeze: subsystem-level freezing instead of total freeze.
    
    Allows freezing rebid and rescue_taker while keeping edge updates active.
    
    Subsystems:
      - rebid: Quote repricing / order replacement
      - rescue_taker: Taker rescue trades
      - edge: Edge calculations (never frozen)
    
    Usage:
        freeze = PartialFreezeState()
        
        # Activate freeze for specific subsystems
        freeze.activate(subsystems=['rebid', 'rescue_taker'], reason='oscillation')
        
        # Check if subsystem frozen
        if freeze.is_frozen('rebid'):
            print("Skip rebid this iteration")
        
        # Deactivate after cooldown
        freeze.deactivate()
    """
    
    def __init__(self):
        self.frozen_subsystems: List[str] = []
        self.freeze_reason: str = ""
        self.freeze_start_ms: Optional[float] = None
        self.min_freeze_duration_ms = 3000  # Minimum 3s freeze
    
    def activate(self, subsystems: List[str], reason: str = ""):
        """
        Activate partial freeze for specific subsystems.
        
        Args:
            subsystems: List of subsystem names to freeze
            reason: Reason for freeze (for logging)
        """
        self.frozen_subsystems = list(subsystems)
        self.freeze_reason = reason
        self.freeze_start_ms = time.time() * 1000
    
    def deactivate(self) -> bool:
        """
        Attempt to deactivate freeze.
        
        Returns:
            True if deactivated, False if still in minimum freeze period
        """
        if not self.frozen_subsystems:
            return True
        
        now_ms = time.time() * 1000
        elapsed_ms = now_ms - (self.freeze_start_ms or now_ms)
        
        if elapsed_ms >= self.min_freeze_duration_ms:
            self.frozen_subsystems = []
            self.freeze_reason = ""
            self.freeze_start_ms = None
            return True
        
        return False
    
    def is_frozen(self, subsystem: str) -> bool:
        """Check if specific subsystem is frozen."""
        return subsystem in self.frozen_subsystems
    
    def is_any_frozen(self) -> bool:
        """Check if any subsystem is frozen."""
        return len(self.frozen_subsystems) > 0
    
    def get_status(self) -> Dict[str, Any]:
        """Get freeze status dict."""
        if not self.frozen_subsystems:
            return {
                "active": False,
                "subsystems": [],
                "reason": ""
            }
        
        now_ms = time.time() * 1000
        elapsed_ms = now_ms - (self.freeze_start_ms or now_ms)
        
        return {
            "active": True,
            "subsystems": list(self.frozen_subsystems),
            "reason": self.freeze_reason,
            "elapsed_ms": elapsed_ms
        }


def apply_partial_freeze(
    proposed_deltas: Dict[str, float],
    freeze_state: PartialFreezeState
) -> Dict[str, float]:
    """
    Apply partial freeze: remove deltas for frozen subsystems.
    
    Args:
        proposed_deltas: Dict of parameter deltas
        freeze_state: Current freeze state
    
    Returns:
        Filtered deltas (only non-frozen subsystems)
    """
    if not freeze_state.is_any_frozen():
        return proposed_deltas
    
    # Map parameters to subsystems
    subsystem_map = {
        # Rebid subsystem (quote repricing)
        'base_spread_bps_delta': 'rebid',
        'replace_rate_per_min': 'rebid',
        'min_interval_ms': 'rebid',
        'rebid_threshold_bps': 'rebid',
        
        # Rescue taker subsystem
        'rescue_max_ratio': 'rescue_taker',
        'rescue_spread_cap_bps': 'rescue_taker',
        
        # Edge subsystem (never frozen)
        'impact_cap_ratio': 'edge',
        'tail_age_ms': 'edge',
        'concurrency_limit': 'edge',
    }
    
    filtered = {}
    for key, value in proposed_deltas.items():
        subsystem = subsystem_map.get(key, 'unknown')
        
        if freeze_state.is_frozen(subsystem):
            # Skip this delta (frozen)
            continue
        
        filtered[key] = value
    
    return filtered


def check_oscillation_guard(
    history: List[Dict[str, float]],
    window: int = 5,
    threshold: float = 0.15
) -> bool:
    """
    Check if oscillation detected in recent deltas.
    
    Args:
        history: List of delta dicts from recent iterations
        window: Number of iterations to check
        threshold: Oscillation threshold (e.g., 0.15 = 15% range)
    
    Returns:
        True if oscillation detected
    """
    if len(history) < window:
        return False
    
    recent = history[-window:]
    
    # Check each parameter for oscillation
    for key in recent[0].keys():
        values = [d.get(key, 0) for d in recent]
        
        if not values:
            continue
        
        value_range = max(values) - min(values)
        mean_abs = sum(abs(v) for v in values) / len(values)
        
        if mean_abs > 0 and (value_range / mean_abs) > threshold:
            return True
    
    return False


def check_latency_buffer_hard(p95_latency_ms: float) -> bool:
    """
    Check if hard latency buffer triggered (p95 >= 360ms).
    
    Returns:
        True if hard buffer triggered
    """
    return p95_latency_ms >= 360.0


def get_guard_recommendation(
    p95_latency_ms: float,
    delta_history: List[Dict[str, float]],
    freeze_state: PartialFreezeState,
    debounce_oscillation: Debounce,
    debounce_latency_hard: Debounce
) -> Dict[str, Any]:
    """
    Consolidated guard check with debouncing and partial freeze.
    
    Args:
        p95_latency_ms: Current P95 latency
        delta_history: Recent delta history
        freeze_state: Current freeze state
        debounce_oscillation: Oscillation debounce
        debounce_latency_hard: Latency hard debounce
    
    Returns:
        Dict with guard recommendation:
          - action: "partial_freeze", "continue_freeze", "clear", "none"
          - subsystems: List of subsystems to freeze
          - reason: Reason string
    """
    # Check signals
    oscillation = check_oscillation_guard(delta_history)
    latency_hard = check_latency_buffer_hard(p95_latency_ms)
    
    # Update debounces
    osc_changed = debounce_oscillation.update(oscillation)
    lat_changed = debounce_latency_hard.update(latency_hard)
    
    # Determine action
    if debounce_oscillation.is_active() or debounce_latency_hard.is_active():
        # Activate or continue freeze
        subsystems = ['rebid']
        reason = ""
        
        if debounce_oscillation.is_active():
            reason = "oscillation"
            subsystems.append('rescue_taker')
        
        if debounce_latency_hard.is_active():
            reason = "latency_hard" if not reason else f"{reason}+latency_hard"
        
        if freeze_state.is_any_frozen():
            action = "continue_freeze"
        else:
            action = "partial_freeze"
        
        return {
            "action": action,
            "subsystems": subsystems,
            "reason": reason
        }
    
    else:
        # Try to clear freeze
        if freeze_state.is_any_frozen():
            if freeze_state.deactivate():
                return {
                    "action": "clear",
                    "subsystems": [],
                    "reason": ""
                }
            else:
                return {
                    "action": "continue_freeze",
                    "subsystems": freeze_state.frozen_subsystems,
                    "reason": "min_duration"
                }
        
        return {
            "action": "none",
            "subsystems": [],
            "reason": ""
        }


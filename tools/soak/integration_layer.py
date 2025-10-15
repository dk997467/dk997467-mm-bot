#!/usr/bin/env python3
"""
Integration Layer for Soak Test Guards and KPI Gates.

Coordinates oscillation detection, velocity bounds, cooldown, and KPI gates.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import os

# Import guards
from tools.soak.iter_watcher import oscillates, within_velocity, apply_cooldown_if_needed
from tools.soak.kpi_gate import kpi_gate_check, format_kpi_summary
from tools.common.jsonx import write_json, compute_json_hash


class GuardsCoordinator:
    """
    Coordinates all guards and checks for soak test.
    
    Tracks:
    - Parameter history (for oscillation detection)
    - Cooldown state
    - KPI gate violations
    - State hashes
    """
    
    def __init__(self):
        self.param_history: Dict[str, List[float]] = {}
        self.cooldown_remaining = 0
        self.kpi_mode = os.environ.get("KPI_GATE_MODE", "soft")
        
        # Metrics counters
        self.oscillation_suppressed_total = 0
        self.velocity_blocked_total = 0
        self.cooldown_skips_total = 0
        self.kpi_violations_total = 0
    
    def check_guards(
        self,
        param_name: str,
        old_value: float,
        new_value: float,
        elapsed_hours: float = 1.0
    ) -> Dict[str, Any]:
        """
        Check all guards for a parameter change.
        
        Returns:
            Dict with:
                - allowed: bool
                - reason: str
                - oscillation_detected: bool
                - velocity_violation: bool
                - cooldown_active: bool
        """
        # Track history
        if param_name not in self.param_history:
            self.param_history[param_name] = []
        
        history = self.param_history[param_name]
        history.append(new_value)
        
        # Keep last 10 values
        if len(history) > 10:
            history.pop(0)
        
        # Check oscillation
        if len(history) >= 3:
            if oscillates(history, window=3):
                self.oscillation_suppressed_total += 1
                return {
                    "allowed": False,
                    "reason": "oscillation_detected",
                    "oscillation_detected": True,
                    "velocity_violation": False,
                    "cooldown_active": False
                }
        
        # Check velocity bounds
        max_change_per_hour = 0.10  # 10 BPS/hour for spreads
        if not within_velocity(old_value, new_value, max_change_per_hour, elapsed_hours):
            self.velocity_blocked_total += 1
            return {
                "allowed": False,
                "reason": "velocity_exceeded",
                "oscillation_detected": False,
                "velocity_violation": True,
                "cooldown_active": False
            }
        
        # Check cooldown
        delta_magnitude = abs(new_value - old_value)
        cooldown_result = apply_cooldown_if_needed(
            delta_magnitude,
            threshold=0.10,
            cooldown_iters=3,
            current_cooldown_remaining=self.cooldown_remaining
        )
        
        self.cooldown_remaining = cooldown_result["cooldown_remaining"]
        
        if not cooldown_result["should_apply"]:
            self.cooldown_skips_total += 1
            return {
                "allowed": False,
                "reason": cooldown_result["reason"],
                "oscillation_detected": False,
                "velocity_violation": False,
                "cooldown_active": True,
                "cooldown_remaining": self.cooldown_remaining
            }
        
        # All guards passed
        return {
            "allowed": True,
            "reason": "normal",
            "oscillation_detected": False,
            "velocity_violation": False,
            "cooldown_active": cooldown_result["cooldown_active"],
            "cooldown_remaining": self.cooldown_remaining
        }
    
    def check_kpi_gate(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check KPI gate and update violation counter.
        
        Args:
            metrics: Metrics dict from ITER_SUMMARY
        
        Returns:
            KPI gate result (verdict, reason, violations, warnings)
        """
        result = kpi_gate_check(metrics, mode=self.kpi_mode)
        
        if result["verdict"] == "FAIL":
            self.kpi_violations_total += 1
        
        # Print summary
        summary_line = format_kpi_summary(metrics, result)
        print(summary_line)
        
        return result
    
    def get_metrics(self) -> Dict[str, int]:
        """Get guard metrics counters."""
        return {
            "oscillation_suppressed_total": self.oscillation_suppressed_total,
            "velocity_blocked_total": self.velocity_blocked_total,
            "cooldown_skips_total": self.cooldown_skips_total,
            "kpi_violations_total": self.kpi_violations_total
        }
    
    def reset(self):
        """Reset all state (for testing)."""
        self.param_history.clear()
        self.cooldown_remaining = 0
        self.oscillation_suppressed_total = 0
        self.velocity_blocked_total = 0
        self.cooldown_skips_total = 0
        self.kpi_violations_total = 0


# Global coordinator instance
_coordinator = None

def get_coordinator() -> GuardsCoordinator:
    """Get or create global guards coordinator."""
    global _coordinator
    if _coordinator is None:
        _coordinator = GuardsCoordinator()
    return _coordinator


def compute_state_hash(runtime_overrides_path: Path) -> str:
    """
    Compute deterministic hash of runtime_overrides.json.
    
    Args:
        runtime_overrides_path: Path to runtime_overrides.json
    
    Returns:
        SHA256 hex digest
    """
    if not runtime_overrides_path.exists():
        return "0" * 64  # No file = zero hash
    
    try:
        with open(runtime_overrides_path, 'r') as f:
            import json
            overrides = json.load(f)
        
        return compute_json_hash(overrides)
    except Exception as e:
        print(f"[WARN] Could not compute state hash: {e}")
        return "error"


if __name__ == "__main__":
    # Self-test
    coordinator = GuardsCoordinator()
    
    # Test oscillation detection
    result1 = coordinator.check_guards("spread", 0.14, 0.16, elapsed_hours=1.0)
    assert result1["allowed"] is True
    
    result2 = coordinator.check_guards("spread", 0.16, 0.14, elapsed_hours=1.0)
    assert result2["allowed"] is True
    
    # Third value oscillates back
    result3 = coordinator.check_guards("spread", 0.14, 0.16, elapsed_hours=1.0)
    assert result3["allowed"] is False
    assert result3["oscillation_detected"] is True
    
    print("✅ Self-test PASSED")
    print(f"Metrics: {coordinator.get_metrics()}")


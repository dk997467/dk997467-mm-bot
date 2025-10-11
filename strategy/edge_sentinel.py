#!/usr/bin/env python3
"""
Edge Sentinel - Automatic Edge Performance Monitoring & Profile Switching

Monitors edge BPS metrics and automatically switches trading profiles
when performance degrades.

Rules:
- If ema1h < 0 for 3 consecutive 30-minute windows → switch to Conservative
- If ema24h >= threshold after Conservative → switch back to Moderate
"""

from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, Optional


class EdgeSentinel:
    """Edge performance monitor with automatic profile switching."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize edge sentinel.
        
        Args:
            config: Configuration dict with thresholds and windows
        """
        self.config = config or {
            "ema1h_negative_threshold": 0.0,
            "ema1h_window_minutes": 30,
            "ema1h_consecutive_failures": 3,
            "ema24h_recovery_threshold": 1.5,
            "profiles": {
                "Moderate": {
                    "spread_multiplier": 1.0,
                    "max_inflight": 10,
                    "backoff_ms": 100
                },
                "Conservative": {
                    "spread_multiplier": 1.5,
                    "max_inflight": 5,
                    "backoff_ms": 200
                }
            }
        }
        
        self.current_profile = "Moderate"
        self.ema1h_history = deque(maxlen=self.config["ema1h_consecutive_failures"])
        self.policy_applied_count = 0
    
    def check_ema1h(self, ema1h: float, timestamp: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Check 1-hour EMA and update history.
        
        Returns dict with recommendation and status.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        # Add to history
        self.ema1h_history.append({
            "value": ema1h,
            "timestamp": timestamp,
            "negative": ema1h < self.config["ema1h_negative_threshold"]
        })
        
        # Check if we have enough samples
        if len(self.ema1h_history) < self.config["ema1h_consecutive_failures"]:
            return {
                "action": "monitor",
                "reason": f"Insufficient samples ({len(self.ema1h_history)}/{self.config['ema1h_consecutive_failures']})"
            }
        
        # Check if all recent samples are negative
        all_negative = all(sample["negative"] for sample in self.ema1h_history)
        
        if all_negative and self.current_profile != "Conservative":
            return {
                "action": "switch_to_conservative",
                "reason": f"EMA1h negative for {len(self.ema1h_history)} consecutive windows"
            }
        
        return {
            "action": "monitor",
            "reason": "EMA1h within acceptable range"
        }
    
    def check_ema24h(self, ema24h: float) -> Dict[str, Any]:
        """
        Check 24-hour EMA for recovery.
        
        Returns dict with recommendation and status.
        """
        threshold = self.config["ema24h_recovery_threshold"]
        
        if ema24h >= threshold and self.current_profile == "Conservative":
            return {
                "action": "switch_to_moderate",
                "reason": f"EMA24h recovered to {ema24h:.2f} (threshold: {threshold})"
            }
        
        return {
            "action": "monitor",
            "reason": f"EMA24h at {ema24h:.2f} (threshold: {threshold})"
        }
    
    def apply_profile(self, profile_name: str) -> Dict[str, Any]:
        """
        Apply a trading profile.
        
        Returns profile configuration.
        """
        if profile_name not in self.config["profiles"]:
            return {
                "status": "error",
                "message": f"Unknown profile: {profile_name}"
            }
        
        self.current_profile = profile_name
        self.policy_applied_count += 1
        
        profile_config = self.config["profiles"][profile_name]
        
        return {
            "status": "applied",
            "profile": profile_name,
            "config": profile_config,
            "marker": "EDGE_POLICY_APPLIED",
            "applied_count": self.policy_applied_count
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current sentinel status."""
        return {
            "current_profile": self.current_profile,
            "ema1h_samples": len(self.ema1h_history),
            "policy_applied_count": self.policy_applied_count,
            "last_ema1h": self.ema1h_history[-1]["value"] if self.ema1h_history else None
        }


def main():
    """Example usage."""
    sentinel = EdgeSentinel()
    
    # Simulate degrading performance
    print("Simulating edge degradation:\n")
    
    for i in range(5):
        ema1h = -0.5 - i * 0.1  # Progressively worse
        result = sentinel.check_ema1h(ema1h)
        print(f"Window {i+1}: EMA1h={ema1h:.2f} → {result['action']} ({result['reason']})")
        
        if result["action"] == "switch_to_conservative":
            apply_result = sentinel.apply_profile("Conservative")
            print(f"  → Applied profile: {apply_result['profile']}")
            print(f"  → Marker: {apply_result['marker']}")
            print(f"  → Config: {apply_result['config']}")
            break
    
    print("\nSimulating recovery:\n")
    
    # Check 24h EMA for recovery
    ema24h = 2.0
    result = sentinel.check_ema24h(ema24h)
    print(f"EMA24h={ema24h:.2f} → {result['action']} ({result['reason']})")
    
    if result["action"] == "switch_to_moderate":
        apply_result = sentinel.apply_profile("Moderate")
        print(f"  → Applied profile: {apply_result['profile']}")
    
    print(f"\nFinal status: {sentinel.get_status()}")


if __name__ == "__main__":
    main()


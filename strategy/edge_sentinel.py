#!/usr/bin/env python3
"""
Edge Sentinel - Automatic Edge Performance Monitoring & Profile Switching

Monitors edge BPS metrics and automatically switches trading profiles
when performance degrades.

Rules:
- If ema1h < 0 for 3 consecutive 30-minute windows → switch to Conservative
- If ema24h >= threshold after Conservative → switch back to Moderate

Profile System:
- Supports loading profiles from config/profiles/market_maker_*.json
- Delta fields (*_delta) are applied to base profile values
- Tracks blocking counters and auto-adjusts min_interval_ms if needed
"""

import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional


class EdgeSentinel:
    """Edge performance monitor with automatic profile switching."""
    
    # Base profile values (used when no profile specified or for delta application)
    BASE_PROFILE = {
        "min_interval_ms": 50,
        "tail_age_ms": 700,
        "max_delta_ratio": 0.12,
        "impact_cap_ratio": 0.08,
        "replace_rate_per_min": 400,
        "concurrency_limit": 2,
        "slippage_penalty_coef": 0.0,
        "vip_tilt_cap": 0.0,
        "inventory_tilt_cap": 0.30,
        "base_spread_bps": 0.5,
    }
    
    # Runtime override limits (field -> (min, max))
    RUNTIME_LIMITS = {
        "min_interval_ms": (50, 300),
        "replace_rate_per_min": (120, 360),
        "base_spread_bps_delta": (0.0, 0.6),
        "impact_cap_ratio": (0.04, 0.12),
        "tail_age_ms": (400, 1000),
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, profile_name: Optional[str] = None):
        """
        Initialize edge sentinel.
        
        Args:
            config: Configuration dict with thresholds and windows
            profile_name: Name of profile to load (e.g. 'S1' for market_maker_S1.json)
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
        
        # Profile system additions
        self.profile_name = profile_name
        self.applied_profile = None
        self.base_profile_values = None  # Store base profile before overrides
        self.runtime_overrides = {}  # Current runtime overrides
        self.runtime_adjustments = []  # History of adjustments
        self.blocked_by = {
            "min_interval": 0,
            "concurrency": 0,
            "risk": 0,
            "throttle": 0,
        }
        self.total_iterations = 0
        
        # Load and apply profile if specified
        if profile_name:
            self.load_and_apply_profile(profile_name)
        
        # Load runtime overrides if available
        self.load_runtime_overrides()
    
    def load_profile_from_file(self, profile_name: str) -> Dict[str, Any]:
        """
        Load profile from config/profiles/market_maker_<name>.json
        
        Args:
            profile_name: Profile name (e.g. 'S1' for market_maker_S1.json)
            
        Returns:
            Profile configuration dict
        """
        # Find workspace root (go up from strategy/ to project root)
        current_file = Path(__file__).resolve()
        workspace_root = current_file.parent.parent
        
        profile_path = workspace_root / "config" / "profiles" / f"market_maker_{profile_name}.json"
        
        if not profile_path.exists():
            raise FileNotFoundError(f"Profile not found: {profile_path}")
        
        with open(profile_path, "r", encoding="utf-8") as f:
            profile_data = json.load(f)
        
        return profile_data
    
    def apply_delta_fields(self, base: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply delta fields (*_delta) from profile to base values.
        
        Args:
            base: Base profile values
            profile: Profile with potential delta fields
            
        Returns:
            Merged profile with deltas applied
        """
        result = base.copy()
        
        for key, value in profile.items():
            if key.endswith("_delta"):
                # Remove _delta suffix to get base field name
                base_key = key[:-6]  # Remove '_delta'
                if base_key in result:
                    result[base_key] = result[base_key] + value
                else:
                    # If base field doesn't exist, create it with delta value
                    result[base_key] = value
            else:
                # Non-delta field: direct override
                result[key] = value
        
        return result
    
    def load_and_apply_profile(self, profile_name: str) -> Dict[str, Any]:
        """
        Load profile from file, apply deltas, and store as applied_profile.
        
        Args:
            profile_name: Profile name (e.g. 'S1')
            
        Returns:
            Applied profile configuration
        """
        # Load profile from file
        profile_data = self.load_profile_from_file(profile_name)
        
        # Apply delta fields to base profile
        applied = self.apply_delta_fields(self.BASE_PROFILE, profile_data)
        
        # Store applied profile and base values
        self.applied_profile = applied
        self.base_profile_values = applied.copy()  # Store before runtime overrides
        self.profile_name = profile_name
        
        # Log marker
        print(f"| profile_apply | OK | PROFILE={profile_name} |")
        
        return applied
    
    def load_runtime_overrides(self) -> Dict[str, Any]:
        """
        Load runtime overrides from ENV or file.
        
        Priority:
        1. MM_RUNTIME_OVERRIDES_JSON environment variable (JSON string)
        2. artifacts/soak/runtime_overrides.json file
        
        Returns:
            Runtime overrides dict (empty if none found)
        """
        overrides = {}
        source = None
        
        # Try ENV first
        env_json = os.environ.get("MM_RUNTIME_OVERRIDES_JSON")
        if env_json:
            try:
                overrides = json.loads(env_json)
                source = "env"
            except json.JSONDecodeError:
                print("| runtime_overrides | ERROR | Invalid JSON in MM_RUNTIME_OVERRIDES_JSON |")
                return {}
        
        # Try file if ENV not found
        if not overrides:
            current_file = Path(__file__).resolve()
            workspace_root = current_file.parent.parent
            overrides_path = workspace_root / "artifacts" / "soak" / "runtime_overrides.json"
            
            if overrides_path.exists():
                try:
                    with open(overrides_path, "r", encoding="utf-8") as f:
                        overrides = json.load(f)
                    source = "file"
                except Exception as e:
                    print(f"| runtime_overrides | ERROR | Failed to read {overrides_path}: {e} |")
                    return {}
        
        # Apply overrides if found
        if overrides:
            self.apply_runtime_overrides(overrides)
            print(f"| runtime_overrides | OK | SOURCE={source} |")
        
        return overrides
    
    def apply_runtime_overrides(self, overrides: Dict[str, Any]):
        """
        Apply runtime overrides to applied_profile with limits enforcement.
        
        Args:
            overrides: Dict of field -> value overrides
        """
        if not self.applied_profile:
            print("| runtime_overrides | SKIP | No profile loaded |")
            return
        
        for field, new_value in overrides.items():
            # Skip if field not in allowed runtime overrides
            if field not in self.RUNTIME_LIMITS:
                print(f"| runtime_override | SKIP | FIELD={field} REASON=not_allowed |")
                continue
            
            # Get old value
            old_value = self.applied_profile.get(field)
            
            # Enforce limits
            min_val, max_val = self.RUNTIME_LIMITS[field]
            clamped_value = max(min_val, min(max_val, new_value))
            
            if clamped_value != new_value:
                print(f"| runtime_override | CLAMP | FIELD={field} FROM={new_value} TO={clamped_value} |")
            
            # Apply override
            self.applied_profile[field] = clamped_value
            self.runtime_overrides[field] = clamped_value
            
            # Track adjustment
            if old_value is not None and old_value != clamped_value:
                self.track_runtime_adjustment(field, old_value, clamped_value, "manual_override")
    
    def track_runtime_adjustment(self, field: str, from_value: Any, to_value: Any, reason: str):
        """
        Track a runtime adjustment in history.
        
        Args:
            field: Field name that was adjusted
            from_value: Previous value
            to_value: New value
            reason: Reason for adjustment
        """
        # Get timestamp
        if 'MM_FREEZE_UTC_ISO' in os.environ:
            ts = os.environ['MM_FREEZE_UTC_ISO']
        else:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        adjustment = {
            "ts": ts,
            "field": field,
            "from": from_value,
            "to": to_value,
            "reason": reason
        }
        
        self.runtime_adjustments.append(adjustment)
        
        # Print marker
        print(f"| runtime_adjust | OK | FIELD={field} FROM={from_value} TO={to_value} REASON={reason} |")
    
    def record_block(self, block_type: str):
        """
        Record a blocking event.
        
        Args:
            block_type: Type of block ('min_interval', 'concurrency', 'risk', 'throttle')
        """
        if block_type in self.blocked_by:
            self.blocked_by[block_type] += 1
    
    def check_and_adjust_min_interval(self):
        """
        Check if min_interval blocking is excessive and auto-adjust.
        
        If blocked_by.min_interval > 25% of total iterations,
        increase min_interval_ms by +10ms for this iteration.
        """
        if self.total_iterations == 0:
            return
        
        if not self.applied_profile:
            return
        
        min_interval_blocks = self.blocked_by["min_interval"]
        block_rate = min_interval_blocks / self.total_iterations
        
        if block_rate > 0.25:
            # Auto-adjust: increase min_interval_ms by 10ms
            old_value = self.applied_profile.get("min_interval_ms", 50)
            new_value = old_value + 10
            self.applied_profile["min_interval_ms"] = new_value
            
            print(f"| min_interval_adjust | block_rate={block_rate:.2%} | {old_value}ms -> {new_value}ms |")
    
    def save_applied_profile(self, output_path: Optional[str] = None):
        """
        Save applied profile to artifacts/soak/applied_profile.json
        
        Includes:
        - profile: Profile name (e.g. "S1")
        - base: Base profile values (before runtime overrides)
        - overrides_runtime: Current runtime overrides
        - runtime_adjustments: History of runtime adjustments
        - applied: Final applied profile (with all overrides)
        
        Args:
            output_path: Custom output path (default: artifacts/soak/applied_profile.json)
        """
        if not self.applied_profile:
            print("| save_applied_profile | SKIP | No profile applied |")
            return
        
        # Determine output path
        if output_path is None:
            current_file = Path(__file__).resolve()
            workspace_root = current_file.parent.parent
            output_path = workspace_root / "artifacts" / "soak" / "applied_profile.json"
        else:
            output_path = Path(output_path)
        
        # Ensure directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Build comprehensive profile data
        profile_data = {
            "profile": self.profile_name or "unknown",
            "base": self.base_profile_values or {},
            "overrides_runtime": self.runtime_overrides,
            "runtime_adjustments": self.runtime_adjustments,
            "applied": self.applied_profile
        }
        
        # Save with deterministic formatting
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                profile_data,
                f,
                sort_keys=True,
                separators=(',', ':'),
                ensure_ascii=False,
                indent=2  # Pretty format for readability
            )
        
        print(f"| save_applied_profile | OK | {output_path} |")
    
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
    """CLI entry point with --dry-run and --profile support."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Edge Sentinel - Market Maker Profile System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run with S1 profile
  MM_PROFILE=S1 python -m strategy.edge_sentinel --dry-run
  
  # Load and apply profile
  python -m strategy.edge_sentinel --profile S1
  
  # Simulate edge monitoring (legacy)
  python -m strategy.edge_sentinel
        """
    )
    
    parser.add_argument(
        "--profile",
        type=str,
        help="Profile name to load (e.g. S1 for market_maker_S1.json)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load profile and show applied config without running"
    )
    
    parser.add_argument(
        "--save-profile",
        action="store_true",
        default=True,
        help="Save applied profile to artifacts/soak/applied_profile.json (default: True)"
    )
    
    args = parser.parse_args()
    
    # Check for MM_PROFILE env var (takes precedence over --profile)
    profile_name = os.environ.get("MM_PROFILE") or args.profile
    
    if profile_name:
        print("=" * 60)
        print(f"Loading profile: {profile_name}")
        print("=" * 60)
        
        try:
            sentinel = EdgeSentinel(profile_name=profile_name)
            
            print("\nApplied profile configuration:")
            print("-" * 60)
            for key, value in sorted(sentinel.applied_profile.items()):
                print(f"  {key:30s} = {value}")
            print("-" * 60)
            
            if args.save_profile:
                sentinel.save_applied_profile()
            
            if args.dry_run:
                print("\n[OK] Dry run complete - profile loaded successfully")
                return
            
            # In production, this would integrate with actual trading logic
            print("\n[OK] Profile loaded and ready for trading")
            
        except FileNotFoundError as e:
            print(f"\n[ERROR] {e}")
            return 1
        except Exception as e:
            print(f"\n[ERROR] Failed to load profile: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    else:
        # Legacy mode: simulate edge monitoring
        print("=" * 60)
        print("Legacy Mode: Edge Monitoring Simulation")
        print("=" * 60)
        print("\nTip: Use --profile S1 or MM_PROFILE=S1 to load custom profile\n")
        
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
    import sys
    sys.exit(main() or 0)


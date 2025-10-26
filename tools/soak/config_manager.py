#!/usr/bin/env python3
"""
Soak test configuration manager with profile loading and runtime overrides.

Usage:
    from tools.soak.config_manager import ConfigManager
    
    cfg = ConfigManager(profile_name="moderate")
    cfg.load()
    
    touch_dwell = cfg.get("touch_dwell_ms", 25)
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_PROFILE = {
    "touch_dwell_ms": 25,
    "min_lot": 0.001,
    "risk_limit": 0.40,
    "latency_p95_limit_ms": 350,
    "maker_taker_min": 0.83,
}


@dataclass
class ConfigManager:
    """
    Configuration manager for soak tests.
    
    Loads configuration from:
    1. Default profile (built-in)
    2. Profile file (profiles/{profile_name}.json)
    3. Environment variables (SOAK_*)
    4. Runtime overrides file (optional)
    
    Writes final config to runtime_overrides.json for reproducibility.
    """
    
    profile_name: str = "default"
    profiles_path: Optional[str] = None
    runtime_overrides_path: str = "artifacts/soak/latest/runtime_overrides.json"
    data: Dict[str, Any] = field(default_factory=dict)
    
    def load(self) -> Dict[str, Any]:
        """
        Load configuration from all sources.
        
        Returns:
            Final merged configuration dict
        """
        data = DEFAULT_PROFILE.copy()
        
        # 1. Load profile file
        profile_file = self._find_profile_file()
        if profile_file:
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    profile_data = json.load(f)
                    data.update(profile_data)
            except Exception as e:
                print(f"[WARN] Failed to load profile {profile_file}: {e}")
        
        # 2. Apply environment overrides
        for key in list(data.keys()):
            env_key = f"SOAK_{key.upper()}"
            if env_key in os.environ:
                value = os.environ[env_key]
                
                # Try to parse as JSON (for complex values)
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    # Keep as string
                    pass
                
                data[key] = value
        
        # 3. Write runtime overrides (for reproducibility)
        self._write_runtime_overrides(data)
        
        self.data = data
        return data
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
        
        Returns:
            Configuration value
        """
        if not self.data:
            self.load()
        
        return self.data.get(key, default)
    
    def _find_profile_file(self) -> Optional[Path]:
        """Find profile file in profiles/ directory."""
        # Check custom path first
        if self.profiles_path:
            profile_file = Path(self.profiles_path) / f"{self.profile_name}.json"
            if profile_file.exists():
                return profile_file
        
        # Check default profiles/ directory
        profile_file = Path("profiles") / f"{self.profile_name}.json"
        if profile_file.exists():
            return profile_file
        
        return None
    
    def _write_runtime_overrides(self, data: Dict[str, Any]) -> None:
        """Write runtime overrides to file."""
        output = {
            "profile": self.profile_name,
            "data": data,
            "source": "ConfigManager"
        }
        
        # Ensure directory exists
        Path(self.runtime_overrides_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.runtime_overrides_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # Smoke test
    print("ConfigManager Smoke Test")
    print("=" * 60)
    
    cfg = ConfigManager(profile_name="default")
    data = cfg.load()
    
    print(f"Profile: {cfg.profile_name}")
    print(f"Config keys: {list(data.keys())}")
    print(f"touch_dwell_ms: {cfg.get('touch_dwell_ms')}")
    print(f"risk_limit: {cfg.get('risk_limit')}")
    
    # Check runtime overrides file
    overrides_path = Path(cfg.runtime_overrides_path)
    if overrides_path.exists():
        print(f"\n[OK] Runtime overrides written to: {overrides_path}")
        print(f"  Size: {overrides_path.stat().st_size} bytes")
    else:
        print(f"\n[FAIL] Runtime overrides not found: {overrides_path}")
    
    print("\n[OK] Smoke test passed")

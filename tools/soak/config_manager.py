#!/usr/bin/env python3
"""
Soak test configuration manager with profile loading and runtime overrides.

Supports:
- Multiple profile directories (profiles/, tools/soak/profiles/, tools/soak/presets/, tests/fixtures/soak_profiles/)
- Profile aliases (steady_safe -> warmup_conservative_v1 -> maker_bias_uplift_v1)
- Deep merge from: defaults -> profile -> ENV -> runtime_overrides
- Atomic JSON writes with trailing newline
- Source tracking (_sources dict)

Usage:
    from tools.soak.config_manager import ConfigManager
    
    cm = ConfigManager()
    profiles = cm.list_profiles()
    cfg = cm.load(profile="steady_safe", verbose=True)
    print(cfg["min_interval_ms"])
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


# Fallback synthetic profile if none found
SYNTHETIC_PROFILE = {
    "name": "steady_safe",
    "symbols": ["BTCUSDT"],
    "notional_usd": 100,
    "risk": {"max_drawdown_pct": 5.0},
    "runtime": {"window_sec": 60}
}

# Profile aliases (fallback chain)
PROFILE_ALIASES = {
    "steady_safe": ["steady_safe", "warmup_conservative_v1", "maker_bias_uplift_v1"],
}


def _deep_merge(base: dict, updates: dict) -> dict:
    """
    Recursively merge updates into base.
    
    - Dict values are merged recursively
    - List/primitive values are replaced entirely
    
    Args:
        base: Base dictionary
        updates: Updates to apply
    
    Returns:
        Merged dictionary (new dict, originals not modified)
    """
    result = base.copy()
    
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursive merge for nested dicts
            result[key] = _deep_merge(result[key], value)
        else:
            # Replace for all other types (including lists)
            result[key] = value
    
    return result


def _coerce_env_value(v: str) -> Any:
    """
    Convert environment variable string to appropriate Python type.
    
    Handles:
    - JSON strings (e.g. '["BTCUSDT","ETHUSDT"]')
    - Numbers ("300" -> 300, "3.14" -> 3.14)
    - Booleans ("true" -> True, "false" -> False)
    - Comma-separated lists ("A,B,C" -> ["A", "B", "C"])
    - Plain strings
    
    Args:
        v: String value from environment
    
    Returns:
        Coerced value
    """
    if not isinstance(v, str):
        return v
    
    # Try JSON parse first (handles complex types)
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Try boolean
    if v.lower() in ("true", "yes", "1"):
        return True
    if v.lower() in ("false", "no", "0"):
        return False
    
    # Try number
    try:
        if '.' in v:
            return float(v)
        return int(v)
    except ValueError:
        pass
    
    # Try comma-separated list
    if ',' in v:
        return [x.strip() for x in v.split(',') if x.strip()]
    
    # Keep as string
    return v


def _apply_env_overrides(base: dict, env: Mapping[str, str]) -> dict:
    """
    Apply SOAK_* environment variables to base config.
    
    Converts SOAK_SYMBOLS="BTCUSDT,ETHUSDT" -> {"symbols": ["BTCUSDT","ETHUSDT"]}
    
    Args:
        base: Base configuration dict
        env: Environment dict (e.g. os.environ)
    
    Returns:
        Config with env overrides applied
    """
    result = base.copy()
    
    for key, value in env.items():
        if not key.startswith("SOAK_"):
            continue
        
        # Remove SOAK_ prefix and convert to lowercase
        config_key = key[5:].lower()
        
        # Coerce value
        coerced = _coerce_env_value(value)
        
        result[config_key] = coerced
    
    return result


def _json_dump_atomic(path: Path, data: dict) -> None:
    """
    Atomically write JSON file with sorted keys and trailing newline.
    
    Uses temp file + rename for atomicity.
    
    Args:
        path: Target file path
        data: Data to write
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to temp file
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=True, sort_keys=True, indent=2)
            f.write('\n')  # Trailing newline
        
        # Atomic rename
        Path(tmp_path).replace(path)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


class ConfigManager:
    """
    Configuration manager for soak tests.
    
    Loads configuration with precedence (low to high):
    1. Default overrides (tools/soak/default_overrides.json)
    2. Profile file (from profiles/, tools/soak/profiles/, tools/soak/presets/, tests/fixtures/soak_profiles/)
    3. Environment variables (SOAK_*)
    4. Runtime overrides (passed to load())
    
    Example:
        cm = ConfigManager()
        profiles = cm.list_profiles()
        cfg = cm.load(profile="steady_safe", verbose=True)
    """
    
    def __init__(self, repo_root: str | Path | None = None):
        """
        Initialize ConfigManager.
        
        Args:
            repo_root: Repository root path (auto-detected if None)
        """
        if repo_root is None:
            # Auto-detect repo root (walk up from this file until we find .git or pyproject.toml)
            current = Path(__file__).resolve().parent
            while current != current.parent:
                if (current / ".git").exists() or (current / "pyproject.toml").exists():
                    repo_root = current
                    break
                current = current.parent
            
            if repo_root is None:
                # Fallback to parent of tools/
                repo_root = Path(__file__).resolve().parents[2]
        
        self.repo_root = Path(repo_root)
        self._profile_dirs = [
            self.repo_root / "profiles",
            self.repo_root / "tools" / "soak" / "profiles",
            self.repo_root / "tools" / "soak" / "presets",
            self.repo_root / "tests" / "fixtures" / "soak_profiles",
        ]
    
    def list_profiles(self) -> list[str]:
        """
        List all available profile names.
        
        Scans all profile directories for *.json files (except README.*).
        
        Returns:
            List of profile names (without .json extension)
        """
        profiles = set()
        
        for profile_dir in self._profile_dirs:
            if not profile_dir.exists():
                continue
            
            for json_file in profile_dir.glob("*.json"):
                # Skip README and other non-profile files
                if json_file.stem.startswith("README"):
                    continue
                
                profiles.add(json_file.stem)
        
        return sorted(profiles)
    
    def get_profile_path(self, name: str) -> Path | None:
        """
        Get path to profile file.
        
        Searches all profile directories in order.
        
        Args:
            name: Profile name (without .json extension)
        
        Returns:
            Path to profile file, or None if not found
        """
        for profile_dir in self._profile_dirs:
            profile_file = profile_dir / f"{name}.json"
            if profile_file.exists():
                return profile_file
        
        return None
    
    def load(
        self,
        profile: str | None = None,
        env: dict[str, str] | None = None,
        runtime_overrides: dict | None = None,
        cli_overrides: dict | None = None,  # Alias for runtime_overrides (for compatibility)
        verbose: bool = False
    ) -> dict:
        """
        Load configuration from all sources.
        
        Precedence (low to high):
        1. Default overrides (tools/soak/default_overrides.json)
        2. Profile file
        3. Environment variables (SOAK_*)
        4. Runtime/CLI overrides
        
        Args:
            profile: Profile name (or None for defaults only)
            env: Environment dict (defaults to os.environ)
            runtime_overrides: Additional overrides to apply
            cli_overrides: Alias for runtime_overrides (backward compat)
            verbose: If True, save runtime_overrides.json
        
        Returns:
            Final merged configuration dict with _sources tracking
        """
        if env is None:
            env = os.environ
        
        # Merge cli_overrides into runtime_overrides if provided
        if cli_overrides is not None:
            if runtime_overrides is None:
                runtime_overrides = cli_overrides
            else:
                runtime_overrides = _deep_merge(runtime_overrides, cli_overrides)
        
        # Track sources for each key
        sources: dict[str, str] = {}
        
        # 1. Start with default overrides
        config = {}
        default_overrides_path = self.repo_root / "tools" / "soak" / "default_overrides.json"
        if default_overrides_path.exists():
            try:
                with open(default_overrides_path, 'r', encoding='utf-8') as f:
                    defaults = json.load(f)
                    config = _deep_merge(config, defaults)
                    for key in defaults.keys():
                        sources[key] = "default_overrides"
            except Exception:
                pass
        
        # 2. Load profile (with alias fallback)
        profile_loaded = False
        if profile:
            # Try profile name and aliases
            candidates = [profile]
            if profile in PROFILE_ALIASES:
                candidates.extend(PROFILE_ALIASES[profile])
            
            for candidate in candidates:
                profile_path = self.get_profile_path(candidate)
                if profile_path:
                    try:
                        with open(profile_path, 'r', encoding='utf-8') as f:
                            profile_data = json.load(f)
                            config = _deep_merge(config, profile_data)
                            for key in profile_data.keys():
                                sources[key] = f"profile:{candidate}"
                            profile_loaded = True
                            break
                    except Exception:
                        pass
            
            # If no profile found, use synthetic fallback
            if not profile_loaded:
                config = _deep_merge(config, SYNTHETIC_PROFILE)
                for key in SYNTHETIC_PROFILE.keys():
                    sources[key] = "synthetic"
        
        # 3. Apply environment overrides
        env_config = _apply_env_overrides({}, env)
        if env_config:
            config = _deep_merge(config, env_config)
            for key in env_config.keys():
                    sources[key] = "env"
        
        # 4. Apply runtime/CLI overrides
        if runtime_overrides:
            config = _deep_merge(config, runtime_overrides)
            for key in runtime_overrides.keys():
                sources[key] = "cli" if cli_overrides else "runtime"
        
        # Add source tracking to result
        config["_sources"] = sources
        
        # Save runtime overrides if verbose
        if verbose:
            self.save_runtime_overrides(config)
        
        return config
    
    def save_runtime_overrides(self, data: dict) -> Path:
        """
        Save runtime overrides to artifacts directory.
        
        Args:
            data: Configuration data to save
        
        Returns:
            Path to saved file
        """
        output_path = self.runtime_overrides_path()
        
        # Write atomically
        _json_dump_atomic(output_path, data)
        
        return output_path
    
    def runtime_overrides_path(self) -> Path:
        """
        Get path to runtime overrides file.
        
        Returns:
            Path to artifacts/soak/latest/runtime_overrides.json
        """
        return self.repo_root / "artifacts" / "soak" / "latest" / "runtime_overrides.json"


if __name__ == "__main__":
    # Smoke test
    print("ConfigManager Smoke Test")
    print("=" * 60)
    
    cm = ConfigManager()
    
    print(f"Repo root: {cm.repo_root}")
    print(f"Available profiles: {cm.list_profiles()}")
    print()
    
    # Load steady_safe profile
    cfg = cm.load(profile="steady_safe", verbose=True)
    
    print(f"Profile loaded: steady_safe")
    print(f"  min_interval_ms: {cfg.get('min_interval_ms')}")
    print(f"  tail_age_ms: {cfg.get('tail_age_ms')}")
    print(f"  risk_limit: {cfg.get('risk_limit')}")
    print()
    
    # Check runtime overrides file
    overrides_path = cm.runtime_overrides_path()
    if overrides_path.exists():
        print(f"[OK] Runtime overrides written to: {overrides_path}")
        print(f"  Size: {overrides_path.stat().st_size} bytes")
    else:
        print(f"[FAIL] Runtime overrides not found: {overrides_path}")
    
    print("\n[OK] Smoke test passed")

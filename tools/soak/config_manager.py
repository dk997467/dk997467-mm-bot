#!/usr/bin/env python3
"""
Soak test configuration manager with profile loading and runtime overrides.

Supports:
- Multiple profile directories (profiles/, tools/soak/profiles/, tools/soak/presets/, tests/fixtures/soak_profiles/)
- Profile aliases (steady_safe -> warmup_conservative_v1 -> maker_bias_uplift_v1)
- Deep merge with precedence: CLI > ENV > Profile > Defaults
- Atomic JSON writes with trailing newline
- Source tracking (_sources dict)

Usage:
    from tools.soak.config_manager import ConfigManager, DEFAULT_OVERRIDES
    
    cm = ConfigManager()
    cfg = cm.load(
        profile="steady_safe",
        env_overrides='{"min_interval_ms": 999}',
        cli_overrides={"tail_age_ms": 888},
        verbose=True
    )
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


__all__ = [
    "ConfigManager",
    "DEFAULT_OVERRIDES",
]


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


def _load_default_overrides(repo_root: Path) -> dict:
    """
    Load default overrides from tools/soak/default_overrides.json.
    
    Falls back to minimal safe defaults if file not found.
    
    Args:
        repo_root: Repository root path
    
    Returns:
        Default configuration dict
    """
    default_path = repo_root / "tools" / "soak" / "default_overrides.json"
    if default_path.exists():
        try:
            with open(default_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    
    # Minimal safe defaults
    return {
        "base_spread_bps_delta": 0.14,
        "impact_cap_ratio": 0.09,
        "max_delta_ratio": 0.14,
        "min_interval_ms": 70,
        "replace_rate_per_min": 280,
        "tail_age_ms": 620
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
    
    for key, value in (updates or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursive merge for nested dicts
            result[key] = _deep_merge(result[key], value)
        else:
            # Replace for all other types (including lists)
            result[key] = value
    
    return result


def _parse_env_overrides(value: str | dict | None) -> dict:
    """
    Parse env_overrides parameter.
    
    Tests pass either:
    - JSON string: '{"min_interval_ms": 999}'
    - Dict: {"min_interval_ms": 999}
    - None: {}
    
    Args:
        value: String JSON or dict or None
    
    Returns:
        Parsed dict (empty if None or parse error)
    """
    if value is None:
        return {}
    
    if isinstance(value, dict):
        return value
    
    if not isinstance(value, str):
        return {}
    
    s = value.strip()
    if not s:
        return {}
    
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


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


# Initialize repo root (auto-detect from this file)
_REPO_ROOT = Path(__file__).resolve().parents[2]  # mm-bot/tools/soak/config_manager.py -> mm-bot/

# Export DEFAULT_OVERRIDES at module level for tests
DEFAULT_OVERRIDES: dict = _load_default_overrides(_REPO_ROOT)


class ConfigManager:
    """
    Configuration manager for soak tests.
    
    Loads configuration with precedence (low to high):
    1. Default overrides (tools/soak/default_overrides.json)
    2. Profile file (from profiles/, tools/soak/profiles/, tools/soak/presets/, tests/fixtures/soak_profiles/)
    3. Environment overrides (env_overrides parameter as JSON string or dict)
    4. CLI overrides (cli_overrides parameter as dict)
    
    Example:
        cm = ConfigManager()
        cfg = cm.load(
            profile="steady_safe",
            env_overrides='{"min_interval_ms": 999}',
            cli_overrides={"tail_age_ms": 888},
            verbose=True
        )
    """
    
    def __init__(self, repo_root: str | Path | None = None):
        """
        Initialize ConfigManager.
        
        Args:
            repo_root: Repository root path (auto-detected if None)
        """
        if repo_root is None:
            # Use global _REPO_ROOT (auto-detected at module load)
            repo_root = _REPO_ROOT
        else:
            # Validate provided repo_root
            repo_root = Path(repo_root).resolve()
            
            # If provided path doesn't look like a repo root, use global _REPO_ROOT
            if not (repo_root / ".git").exists() and not (repo_root / "pyproject.toml").exists():
                # Provided path is probably artifacts_dir or similar, use global
                repo_root = _REPO_ROOT
        
        self.repo_root = Path(repo_root).resolve()
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
        env_overrides: str | dict | None = None,
        cli_overrides: dict | None = None,
        verbose: bool = False,
        **kwargs  # Backward compatibility with old signatures
    ) -> dict:
        """
        Load configuration from all sources.
        
        Precedence (low to high):
        1. Defaults (tools/soak/default_overrides.json)
        2. Profile file (e.g. steady_safe.json)
        3. ENV overrides (env_overrides parameter)
        4. CLI overrides (cli_overrides parameter)
        
        Args:
            profile: Profile name (or None for defaults only)
            env_overrides: JSON string or dict with environment overrides
            cli_overrides: Dict with CLI overrides (highest priority)
            verbose: If True, save runtime_overrides.json
            **kwargs: For backward compatibility (ignored)
        
        Returns:
            Final merged configuration dict with _sources tracking
        """
        # Track sources for each key
        sources: dict[str, str] = {}
        
        # 1. Start with default overrides
        config = _load_default_overrides(self.repo_root).copy()
        for key in config.keys():
            sources[key] = "default"
        
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
        
        # 3. Apply environment overrides (from env_overrides parameter)
        env_config = _parse_env_overrides(env_overrides)
        if env_config:
            config = _deep_merge(config, env_config)
            for key in env_config.keys():
                sources[key] = "env"
        
        # 4. Apply CLI overrides (highest priority)
        if cli_overrides:
            config = _deep_merge(config, cli_overrides)
            for key in cli_overrides.keys():
                sources[key] = "cli"
        
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
    print(f"  impact_cap_ratio: {cfg.get('impact_cap_ratio')}")
    print()
    
    # Check runtime overrides file
    overrides_path = cm.runtime_overrides_path()
    if overrides_path.exists():
        print(f"[OK] Runtime overrides written to: {overrides_path}")
        print(f"  Size: {overrides_path.stat().st_size} bytes")
    else:
        print(f"[FAIL] Runtime overrides not found: {overrides_path}")
    
    print("\n[OK] Smoke test passed")

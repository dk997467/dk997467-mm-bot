#!/usr/bin/env python3
"""
Unified Configuration Manager for Soak Tests.

Implements clear precedence: CLI > Env > Profile > Defaults
Manages immutable profiles and mutable runtime overrides.

Usage:
    from tools.soak.config_manager import ConfigManager
    
    config = ConfigManager()
    overrides = config.load(profile="steady_safe")

CLI:
    # Migrate legacy configs
    python -m tools.soak.config_manager --migrate
    
    # List available profiles
    python -m tools.soak.config_manager --list-profiles
    
    # Show config with precedence
    python -m tools.soak.config_manager --show --profile steady_safe
"""

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List


# Default parameter values (fallback if no profile specified)
DEFAULT_OVERRIDES = {
    "base_spread_bps_delta": 0.14,
    "impact_cap_ratio": 0.09,
    "max_delta_ratio": 0.14,
    "min_interval_ms": 70,
    "replace_rate_per_min": 260,
    "tail_age_ms": 650,
}

# Profile definitions (immutable reference configs)
PROFILES = {
    "steady_safe": {
        "base_spread_bps_delta": 0.16,
        "impact_cap_ratio": 0.08,
        "max_delta_ratio": 0.12,
        "min_interval_ms": 75,
        "replace_rate_per_min": 260,
        "tail_age_ms": 740,
    },
    "ultra_safe": {
        "base_spread_bps_delta": 0.16,
        "impact_cap_ratio": 0.08,
        "max_delta_ratio": 0.12,
        "min_interval_ms": 80,
        "replace_rate_per_min": 240,
        "tail_age_ms": 700,
    },
    "aggressive": {
        "base_spread_bps_delta": 0.10,
        "impact_cap_ratio": 0.12,
        "max_delta_ratio": 0.16,
        "min_interval_ms": 50,
        "replace_rate_per_min": 320,
        "tail_age_ms": 500,
    },
}


class ConfigManager:
    """
    Manages soak test configuration with clear precedence.
    
    Precedence (highest to lowest):
    1. CLI overrides (passed to load())
    2. Environment variable (MM_RUNTIME_OVERRIDES_JSON)
    3. Profile (immutable, from profiles/{name}.json)
    4. Defaults (hardcoded fallback)
    
    Files:
    - profiles/{name}.json — Immutable, version-controlled
    - runtime_overrides.json — Mutable, updated by live-apply
    """
    
    def __init__(self, base_dir: Path = Path("artifacts/soak")):
        self.base_dir = base_dir
        self.profiles_dir = base_dir / "profiles"
        self.runtime_path = base_dir / "runtime_overrides.json"
        
        # Ensure directories exist
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize profiles if they don't exist
        self._initialize_profiles()
    
    def _initialize_profiles(self):
        """Write profile files if they don't exist."""
        for name, params in PROFILES.items():
            profile_path = self.profiles_dir / f"{name}.json"
            if not profile_path.exists():
                with open(profile_path, 'w', encoding='utf-8') as f:
                    json.dump(params, f, indent=2, sort_keys=True)
                print(f"| config | CREATED | profile={name} path={profile_path} |")
    
    def load(
        self,
        profile: Optional[str] = None,
        env_overrides: Optional[str] = None,
        cli_overrides: Optional[Dict[str, Any]] = None,
        verbose: bool = True
    ) -> Dict[str, Any]:
        """
        Load overrides with clear precedence: CLI > Env > Profile > Defaults
        
        Args:
            profile: Profile name (e.g., "steady_safe")
            env_overrides: JSON string from MM_RUNTIME_OVERRIDES_JSON env var
            cli_overrides: Dict of overrides from command line args
            verbose: Print source logging
        
        Returns:
            Merged overrides dict with source annotations
        """
        # Track sources for debugging
        sources = {}
        
        # Layer 0: Start with defaults
        overrides = DEFAULT_OVERRIDES.copy()
        for key in overrides:
            sources[key] = "default"
        
        # Layer 1: Profile (if specified)
        if profile:
            profile_params = self._load_profile(profile)
            if profile_params:
                for key, value in profile_params.items():
                    overrides[key] = value
                    sources[key] = f"profile:{profile}"
                if verbose:
                    print(f"| config | LOADED | source=profile:{profile} params={len(profile_params)} |")
            else:
                if verbose:
                    print(f"| config | WARN | profile={profile} not found, using defaults |")
        
        # Layer 2: Environment variable
        if env_overrides is None:
            env_overrides = os.environ.get("MM_RUNTIME_OVERRIDES_JSON")
        
        if env_overrides:
            try:
                env_params = json.loads(env_overrides)
                for key, value in env_params.items():
                    overrides[key] = value
                    sources[key] = "env"
                if verbose:
                    print(f"| config | LOADED | source=env params={len(env_params)} |")
            except json.JSONDecodeError as e:
                if verbose:
                    print(f"| config | ERROR | Invalid env JSON: {e} |")
        
        # Layer 3: CLI overrides (highest priority)
        if cli_overrides:
            for key, value in cli_overrides.items():
                overrides[key] = value
                sources[key] = "cli"
            if verbose:
                print(f"| config | LOADED | source=cli params={len(cli_overrides)} |")
        
        # Store sources for debugging
        overrides["_sources"] = sources
        
        return overrides
    
    def _load_profile(self, profile: str) -> Optional[Dict[str, Any]]:
        """Get parameters for a specific profile."""
        profile_path = self.profiles_dir / f"{profile}.json"
        if profile_path.exists():
            with open(profile_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    def save_runtime_overrides(self, overrides: Dict[str, Any]):
        """
        Save active runtime overrides to file.
        
        Note: Removes _sources annotation before saving.
        """
        # Remove metadata
        clean_overrides = {k: v for k, v in overrides.items() if not k.startswith("_")}
        
        with open(self.runtime_path, 'w', encoding='utf-8') as f:
            json.dump(clean_overrides, f, indent=2, sort_keys=True)
        print(f"| config | SAVED | path={self.runtime_path} params={len(clean_overrides)} |")
    
    def list_profiles(self) -> List[str]:
        """List available profile names."""
        return sorted(PROFILES.keys())
    
    def show_profile(self, profile: str) -> Optional[Dict[str, Any]]:
        """Show parameters for a specific profile."""
        return self._load_profile(profile)
    
    def show_precedence(
        self,
        profile: Optional[str] = None,
        env_overrides: Optional[str] = None,
        cli_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Show which source each parameter came from.
        
        Returns:
            Dict mapping param -> source
        """
        overrides = self.load(profile, env_overrides, cli_overrides, verbose=False)
        return overrides.get("_sources", {})


def migrate_legacy_configs():
    """
    Migrate legacy config files to new structure.
    
    Converts:
        - steady_safe_overrides.json → profiles/steady_safe.json
        - ultra_safe_overrides.json → profiles/ultra_safe.json
        - steady_overrides.json → DEPRECATED (removed)
        - applied_profile.json → DEPRECATED (removed)
    
    Preserves:
        - runtime_overrides.json (active overrides, updated by live-apply)
    """
    base_dir = Path("artifacts/soak")
    config_mgr = ConfigManager(base_dir)
    
    migrations = []
    
    # Migrate steady_safe
    legacy_steady_safe = base_dir / "steady_safe_overrides.json"
    if legacy_steady_safe.exists():
        target = config_mgr.profiles_dir / "steady_safe.json"
        shutil.move(str(legacy_steady_safe), str(target))
        migrations.append(f"steady_safe_overrides.json -> profiles/steady_safe.json")
        print(f"| migrate | MOVED | {migrations[-1]} |")
    
    # Migrate ultra_safe
    legacy_ultra_safe = base_dir / "ultra_safe_overrides.json"
    if legacy_ultra_safe.exists():
        target = config_mgr.profiles_dir / "ultra_safe.json"
        shutil.move(str(legacy_ultra_safe), str(target))
        migrations.append(f"ultra_safe_overrides.json -> profiles/ultra_safe.json")
        print(f"| migrate | MOVED | {migrations[-1]} |")
    
    # DEPRECATED: Remove steady_overrides.json
    legacy_steady = base_dir / "steady_overrides.json"
    if legacy_steady.exists():
        legacy_steady.unlink()
        migrations.append("steady_overrides.json REMOVED (DEPRECATED)")
        print(f"| migrate | REMOVED | steady_overrides.json (DEPRECATED) |")
    
    # DEPRECATED: Remove applied_profile.json (superseded by runtime_overrides.json)
    legacy_applied = base_dir / "applied_profile.json"
    if legacy_applied.exists():
        # Backup before removing
        backup_path = base_dir / "applied_profile.json.backup"
        shutil.copy(str(legacy_applied), str(backup_path))
        legacy_applied.unlink()
        migrations.append("applied_profile.json REMOVED (backup saved)")
        print(f"| migrate | REMOVED | applied_profile.json (backup: applied_profile.json.backup) |")
    
    # Summary
    print()
    print("=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"Total migrations: {len(migrations)}")
    for m in migrations:
        print(f"  - {m}")
    print()
    print("New structure:")
    print("  artifacts/soak/")
    print("  ├── runtime_overrides.json    (mutable, updated by live-apply)")
    print("  └── profiles/                 (immutable, version-controlled)")
    print("      ├── steady_safe.json")
    print("      ├── ultra_safe.json")
    print("      └── aggressive.json")
    print("=" * 60)


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Manage soak test configs with clear precedence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate legacy configs
  python -m tools.soak.config_manager --migrate

  # List available profiles
  python -m tools.soak.config_manager --list-profiles

  # Show specific profile
  python -m tools.soak.config_manager --show --profile steady_safe

  # Show precedence (what wins)
  python -m tools.soak.config_manager --precedence --profile steady_safe
        """
    )
    
    parser.add_argument("--migrate", action="store_true", help="Migrate legacy config files")
    parser.add_argument("--list-profiles", action="store_true", help="List available profiles")
    parser.add_argument("--show", action="store_true", help="Show profile parameters")
    parser.add_argument("--precedence", action="store_true", help="Show parameter sources")
    parser.add_argument("--profile", type=str, help="Profile name (e.g., steady_safe)")
    
    args = parser.parse_args(argv)
    
    if args.migrate:
        migrate_legacy_configs()
        return 0
    
    config_mgr = ConfigManager()
    
    if args.list_profiles:
        print("Available profiles:")
        for name in config_mgr.list_profiles():
            params = config_mgr.show_profile(name)
            if params:
                print(f"\n{name}:")
                for k, v in sorted(params.items()):
                    if isinstance(v, float):
                        print(f"  {k:30s} = {v:.2f}")
                    else:
                        print(f"  {k:30s} = {v}")
        return 0
    
    if args.show:
        if not args.profile:
            print("[ERROR] --show requires --profile")
            return 1
        
        params = config_mgr.show_profile(args.profile)
        if params:
            print(f"Profile: {args.profile}")
            print(json.dumps(params, indent=2, sort_keys=True))
        else:
            print(f"[ERROR] Profile not found: {args.profile}")
            return 1
        return 0
    
    if args.precedence:
        sources = config_mgr.show_precedence(profile=args.profile)
        print("Parameter sources (precedence: CLI > Env > Profile > Default):")
        print()
        for param, source in sorted(sources.items()):
            print(f"  {param:30s} <- {source}")
        return 0
    
    # Default: just list profiles
    print("Use --list-profiles, --show, --precedence, or --migrate")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())


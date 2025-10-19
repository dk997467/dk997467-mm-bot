"""
Test config precedence: CLI > Env > Profile > Default.

Verifies that ConfigManager respects the documented priority order
and correctly merges conflicting parameter values.
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

# Add tools to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.soak.config_manager import ConfigManager, DEFAULT_OVERRIDES


class TestConfigPrecedence:
    """Test configuration precedence rules."""
    
    def setup_method(self):
        """Create temporary config directory for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_mgr = ConfigManager(Path(self.temp_dir))
    
    def teardown_method(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_defaults_used_when_no_overrides(self):
        """Test that defaults are used when no overrides provided."""
        config = self.config_mgr.load(verbose=False)
        
        # Remove metadata
        config.pop("_sources", None)
        
        assert config == DEFAULT_OVERRIDES
    
    def test_profile_overrides_defaults(self):
        """Test that profile values override defaults."""
        config = self.config_mgr.load(profile="steady_safe", verbose=False)
        
        # steady_safe profile has different values
        assert config["min_interval_ms"] == 75  # vs 70 in defaults
        assert config["tail_age_ms"] == 740  # vs 650 in defaults
        
        # Sources should show profile origin
        sources = config.get("_sources", {})
        assert sources["min_interval_ms"] == "profile:steady_safe"
        assert sources["tail_age_ms"] == "profile:steady_safe"
    
    def test_env_overrides_profile(self):
        """Test that env var overrides profile."""
        env_json = json.dumps({"min_interval_ms": 999})
        
        config = self.config_mgr.load(
            profile="steady_safe",
            env_overrides=env_json,
            verbose=False
        )
        
        # Env should win
        assert config["min_interval_ms"] == 999
        
        # Other params still from profile
        assert config["tail_age_ms"] == 740  # From steady_safe
        
        # Sources should reflect override
        sources = config.get("_sources", {})
        assert sources["min_interval_ms"] == "env"
        assert sources["tail_age_ms"] == "profile:steady_safe"
    
    def test_cli_overrides_env(self):
        """Test that CLI overrides env var."""
        env_json = json.dumps({"min_interval_ms": 999, "tail_age_ms": 888})
        cli_overrides = {"min_interval_ms": 111}  # CLI overrides env
        
        config = self.config_mgr.load(
            profile="steady_safe",
            env_overrides=env_json,
            cli_overrides=cli_overrides,
            verbose=False
        )
        
        # CLI wins for min_interval_ms
        assert config["min_interval_ms"] == 111
        
        # Env wins for tail_age_ms (no CLI override)
        assert config["tail_age_ms"] == 888
        
        # Sources should reflect precedence
        sources = config.get("_sources", {})
        assert sources["min_interval_ms"] == "cli"
        assert sources["tail_age_ms"] == "env"
    
    def test_full_precedence_chain(self):
        """Test all 4 layers: CLI > Env > Profile > Default."""
        env_json = json.dumps({
            "min_interval_ms": 200,  # Env override
            "tail_age_ms": 800       # Env override
        })
        
        cli_overrides = {
            "min_interval_ms": 300   # CLI override (beats env)
        }
        
        config = self.config_mgr.load(
            profile="steady_safe",        # Profile overrides defaults
            env_overrides=env_json,       # Env overrides profile
            cli_overrides=cli_overrides,  # CLI overrides env
            verbose=False
        )
        
        # min_interval_ms: CLI (highest)
        assert config["min_interval_ms"] == 300
        
        # tail_age_ms: Env (no CLI override)
        assert config["tail_age_ms"] == 800
        
        # impact_cap_ratio: Profile (no env/CLI override)
        assert config["impact_cap_ratio"] == 0.08  # From steady_safe
        
        # replace_rate_per_min: Default (no profile/env/CLI override)
        assert config["replace_rate_per_min"] == 260  # From defaults
        
        # Verify sources
        sources = config.get("_sources", {})
        assert sources["min_interval_ms"] == "cli"
        assert sources["tail_age_ms"] == "env"
        assert sources["impact_cap_ratio"] == "profile:steady_safe"
        assert sources["replace_rate_per_min"] == "profile:steady_safe"  # steady_safe also defines this
    
    def test_nonexistent_profile_falls_back_to_defaults(self):
        """Test that invalid profile name falls back to defaults."""
        config = self.config_mgr.load(profile="nonexistent", verbose=False)
        
        # Should use defaults
        config.pop("_sources", None)
        assert config == DEFAULT_OVERRIDES
    
    def test_invalid_json_in_env_is_ignored(self):
        """Test that malformed JSON in env is ignored gracefully."""
        config = self.config_mgr.load(
            env_overrides="not valid json",
            verbose=False
        )
        
        # Should still work with defaults
        config.pop("_sources", None)
        assert config == DEFAULT_OVERRIDES
    
    def test_save_runtime_overrides_removes_metadata(self):
        """Test that _sources metadata is removed when saving."""
        config = self.config_mgr.load(profile="steady_safe", verbose=False)
        
        # Should have _sources
        assert "_sources" in config
        
        # Save to file
        self.config_mgr.save_runtime_overrides(config)
        
        # Read back
        with open(self.config_mgr.runtime_path, 'r') as f:
            saved = json.load(f)
        
        # Metadata should be removed
        assert "_sources" not in saved
        
        # Data should be present
        assert "min_interval_ms" in saved
        assert saved["min_interval_ms"] == 75


class TestConfigMigration:
    """Test legacy config migration."""
    
    def setup_method(self):
        """Create temporary config directory with legacy files."""
        self.temp_dir = tempfile.mkdtemp()
        self.base_dir = Path(self.temp_dir) / "artifacts" / "soak"
        self.base_dir.mkdir(parents=True)
        
        # Create legacy files
        legacy_files = {
            "steady_safe_overrides.json": {"min_interval_ms": 75},
            "ultra_safe_overrides.json": {"min_interval_ms": 80},
            "steady_overrides.json": {"old_param": 123},
            "applied_profile.json": {"old_data": "abc"}
        }
        
        for filename, data in legacy_files.items():
            with open(self.base_dir / filename, 'w') as f:
                json.dump(data, f)
    
    def teardown_method(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_migration_moves_files_to_profiles(self):
        """Test that migration moves legacy files to profiles/ directory."""
        # Change to temp dir for migration
        import os
        old_cwd = os.getcwd()
        os.chdir(self.temp_dir)
        
        try:
            # Run migration
            from tools.soak.config_manager import migrate_legacy_configs
            migrate_legacy_configs()
            
            # Verify profiles directory created
            profiles_dir = self.base_dir / "profiles"
            assert profiles_dir.exists()
            
            # Verify files moved
            assert (profiles_dir / "steady_safe.json").exists()
            assert (profiles_dir / "ultra_safe.json").exists()
            
            # Verify deprecated files removed
            assert not (self.base_dir / "steady_safe_overrides.json").exists()
            assert not (self.base_dir / "ultra_safe_overrides.json").exists()
            assert not (self.base_dir / "steady_overrides.json").exists()
            assert not (self.base_dir / "applied_profile.json").exists()
            
            # Verify backup created for applied_profile
            assert (self.base_dir / "applied_profile.json.backup").exists()
        
        finally:
            os.chdir(old_cwd)


def test_config_manager_list_profiles():
    """Test listing available profiles."""
    config_mgr = ConfigManager()
    profiles = config_mgr.list_profiles()
    
    assert "steady_safe" in profiles
    assert "ultra_safe" in profiles
    assert "aggressive" in profiles
    assert len(profiles) >= 3


def test_config_manager_show_profile():
    """Test showing profile parameters."""
    config_mgr = ConfigManager()
    params = config_mgr.show_profile("steady_safe")
    
    assert params is not None
    assert params["min_interval_ms"] == 75
    assert params["tail_age_ms"] == 740
    assert params["impact_cap_ratio"] == 0.08


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


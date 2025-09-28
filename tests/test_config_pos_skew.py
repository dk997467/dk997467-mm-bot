"""
Unit tests for guards.pos_skew config parsing.
"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.common.config import ConfigLoader, PosSkewConfig, GuardsConfig


def test_config_parses_guards_pos_skew():
    """Test that guards.pos_skew config section is parsed correctly."""
    
    cfg_yaml = (
        "guards:\n"
        "  pos_skew:\n"
        "    per_symbol_abs_limit: 123.0\n"
        "    per_color_abs_limit: 456.0\n"
    )
    
    with TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(cfg_yaml, encoding="utf-8")
        
        loader = ConfigLoader(config_path=str(config_path))
        app_cfg = loader.load()
        
        # Ensure section and keys exist with correct values
        assert hasattr(app_cfg, "guards")
        assert hasattr(app_cfg.guards, "pos_skew")
        assert app_cfg.guards.pos_skew.per_symbol_abs_limit == 123.0
        assert app_cfg.guards.pos_skew.per_color_abs_limit == 456.0


def test_config_guards_pos_skew_defaults():
    """Test that guards.pos_skew uses defaults when section is missing."""
    
    cfg_yaml = "strategy:\n  enable_enhanced_quoting: true\n"
    
    with TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(cfg_yaml, encoding="utf-8")
        
        loader = ConfigLoader(config_path=str(config_path))
        app_cfg = loader.load()
        
        # Should have defaults
        assert hasattr(app_cfg, "guards")
        assert hasattr(app_cfg.guards, "pos_skew")
        assert app_cfg.guards.pos_skew.per_symbol_abs_limit == 0.0
        assert app_cfg.guards.pos_skew.per_color_abs_limit == 0.0


def test_config_guards_pos_skew_validation_negative():
    """Test that negative limits raise ValueError."""
    
    cfg_yaml = (
        "guards:\n"
        "  pos_skew:\n"
        "    per_symbol_abs_limit: -1.0\n"
        "    per_color_abs_limit: 2.0\n"
    )
    
    with TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(cfg_yaml, encoding="utf-8")
        
        loader = ConfigLoader(config_path=str(config_path))
        
        with pytest.raises(ValueError, match="guards.pos_skew.per_symbol_abs_limit must be >= 0.0"):
            loader.load()


def test_config_guards_pos_skew_validation_invalid_type():
    """Test that non-float values raise ValueError."""
    
    cfg_yaml = (
        "guards:\n"
        "  pos_skew:\n"
        "    per_symbol_abs_limit: 'invalid'\n"
        "    per_color_abs_limit: 2.0\n"
    )
    
    with TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(cfg_yaml, encoding="utf-8")
        
        loader = ConfigLoader(config_path=str(config_path))
        
        with pytest.raises(ValueError, match="guards.pos_skew.per_symbol_abs_limit must be a float"):
            loader.load()


def test_config_allocator_smoothing_bias_cap():
    """Test that allocator.smoothing.bias_cap is parsed correctly."""
    
    cfg_yaml = (
        "allocator:\n"
        "  smoothing:\n"
        "    bias_cap: 0.15\n"
    )
    
    with TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(cfg_yaml, encoding="utf-8")
        
        loader = ConfigLoader(config_path=str(config_path))
        app_cfg = loader.load()
        
        # Ensure allocator.smoothing.bias_cap exists with correct value
        assert hasattr(app_cfg, "allocator")
        assert hasattr(app_cfg.allocator, "smoothing")
        assert app_cfg.allocator.smoothing.bias_cap == 0.15


def test_config_allocator_smoothing_defaults():
    """Test that allocator.smoothing uses defaults when section is missing."""
    
    cfg_yaml = "strategy:\n  enable_enhanced_quoting: true\n"
    
    with TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        config_path.write_text(cfg_yaml, encoding="utf-8")
        
        loader = ConfigLoader(config_path=str(config_path))
        app_cfg = loader.load()
        
        # Should have defaults
        assert hasattr(app_cfg, "allocator")
        assert hasattr(app_cfg.allocator, "smoothing")
        assert app_cfg.allocator.smoothing.bias_cap == 0.10  # Default


def test_pos_skew_config_direct():
    """Test PosSkewConfig validation directly."""
    
    # Valid config
    config = PosSkewConfig(per_symbol_abs_limit=1.0, per_color_abs_limit=2.0)
    assert config.per_symbol_abs_limit == 1.0
    assert config.per_color_abs_limit == 2.0
    
    # Test validation in __post_init__
    with pytest.raises(ValueError, match="guards.pos_skew.per_symbol_abs_limit must be >= 0.0"):
        PosSkewConfig(per_symbol_abs_limit=-1.0, per_color_abs_limit=2.0)
    
    with pytest.raises(ValueError, match="guards.pos_skew.per_color_abs_limit must be >= 0.0"):
        PosSkewConfig(per_symbol_abs_limit=1.0, per_color_abs_limit=-1.0)
"""
Test runtime configuration reload functionality.
"""

import pytest
from unittest.mock import Mock, patch

from src.common.config import AppConfig, diff_runtime_safe, apply_runtime_overrides, RUNTIME_MUTABLE
from src.metrics.exporter import Metrics
from src.common.di import AppContext


class TestRuntimeReload:
    """Test runtime configuration reload functionality."""
    
    def test_diff_runtime_safe(self):
        """Test that diff_runtime_safe identifies runtime-safe changes."""
        # Create base config
        base_cfg = AppConfig()
        
        # Create modified config with runtime-safe changes
        modified_cfg = AppConfig()
        modified_cfg.strategy.k_vola_spread = 2.5
        modified_cfg.strategy.levels_per_side = 5
        
        # Get differences
        changes = diff_runtime_safe(base_cfg, modified_cfg)
        
        # Should identify runtime-safe changes
        assert 'strategy.k_vola_spread' in changes
        assert 'strategy.levels_per_side' in changes
        assert len(changes) == 2
    
    def test_diff_runtime_safe_non_runtime(self):
        """Test that diff_runtime_safe ignores non-runtime changes."""
        # Create base config
        base_cfg = AppConfig()
        
        # Create modified config with non-runtime changes
        modified_cfg = AppConfig()
        modified_cfg.bybit.api_key = "new_key"  # Non-runtime field
        
        # Get differences
        changes = diff_runtime_safe(base_cfg, modified_cfg)
        
        # Should not include non-runtime changes
        assert 'bybit.api_key' not in changes
        assert len(changes) == 0
    
    def test_apply_runtime_overrides(self):
        """Test that apply_runtime_overrides applies changes correctly."""
        # Create base config
        base_cfg = AppConfig()
        original_k_vola = base_cfg.strategy.k_vola_spread
        original_levels = base_cfg.strategy.levels_per_side
        
        # Create modified config
        modified_cfg = AppConfig()
        modified_cfg.strategy.k_vola_spread = 3.0
        modified_cfg.strategy.levels_per_side = 6
        
        # Apply overrides
        result_cfg = apply_runtime_overrides(base_cfg, modified_cfg, RUNTIME_MUTABLE)
        
        # Should have new values
        assert result_cfg.strategy.k_vola_spread == 3.0
        assert result_cfg.strategy.levels_per_side == 6
        
        # Note: apply_runtime_overrides modifies the original config
        # This is expected behavior for runtime updates
        assert result_cfg is base_cfg  # Should be the same object
    
    def test_metrics_update_on_reload(self):
        """Test that metrics are updated when config is reloaded."""
        # Clear Prometheus registry
        from prometheus_client import REGISTRY
        REGISTRY._collector_to_names.clear()
        REGISTRY._names_to_collectors.clear()
        
        # Create initial config and metrics
        config = AppConfig()
        ctx = AppContext(cfg=config)
        metrics = Metrics(ctx)
        
        # Store initial values
        initial_k_vola = metrics.cfg_k_vola_spread._value.get()
        initial_levels = metrics.cfg_levels_per_side._value.get()
        
        # Create modified config
        modified_cfg = AppConfig()
        modified_cfg.strategy.k_vola_spread = 4.0
        modified_cfg.strategy.levels_per_side = 8
        
        # Export new config gauges
        metrics.export_cfg_gauges(modified_cfg)
        
        # Metrics should be updated
        new_k_vola = metrics.cfg_k_vola_spread._value.get()
        new_levels = metrics.cfg_levels_per_side._value.get()
        
        # Should reflect new values
        assert new_k_vola == 4.0
        assert new_levels == 8
        
        # Should be different from initial
        assert new_k_vola != initial_k_vola
        assert new_levels != initial_levels
    
    def test_runtime_reload_with_metrics_update(self):
        """Test complete runtime reload flow with metrics update."""
        # Clear Prometheus registry
        from prometheus_client import REGISTRY
        REGISTRY._collector_to_names.clear()
        REGISTRY._names_to_collectors.clear()
        
        # Create initial config and metrics
        config = AppConfig()
        ctx = AppContext(cfg=config)
        metrics = Metrics(ctx)
        
        # Simulate runtime reload
        modified_cfg = AppConfig()
        modified_cfg.strategy.k_vola_spread = 5.0
        modified_cfg.strategy.levels_per_side = 10
        modified_cfg.limits.max_create_per_sec = 20
        modified_cfg.limits.max_cancel_per_sec = 15
        
        # Get changes
        changes = diff_runtime_safe(config, modified_cfg)
        
        # Should identify runtime-safe changes
        assert 'strategy.k_vola_spread' in changes
        assert 'strategy.levels_per_side' in changes
        assert 'limits.max_create_per_sec' in changes
        assert 'limits.max_cancel_per_sec' in changes
        
        # Apply changes
        result_cfg = apply_runtime_overrides(config, modified_cfg, RUNTIME_MUTABLE)
        
        # Update metrics
        metrics.export_cfg_gauges(result_cfg)
        
        # Verify metrics reflect new values
        assert metrics.cfg_k_vola_spread._value.get() == 5.0
        assert metrics.cfg_levels_per_side._value.get() == 10
        assert metrics.cfg_max_create_per_sec._value.get() == 20
        assert metrics.cfg_max_cancel_per_sec._value.get() == 15


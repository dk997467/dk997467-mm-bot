"""
Test configuration system with feature flags and validation.
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, mock_open

from src.common.config import (
    Config, AppConfig, ConfigLoader, get_config, reload_config,
    StrategyConfig, RiskConfig, LimitsConfig, MonitoringConfig
)


class TestStrategyConfig:
    """Test StrategyConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = StrategyConfig()
        
        # Feature flags
        assert config.enable_dynamic_spread is True
        assert config.enable_inventory_skew is True
        assert config.enable_adverse_guard is True
        
        # Spread parameters
        assert config.k_vola_spread == 0.95
        assert config.min_spread_bps == 2
        assert config.max_spread_bps == 25
        
        # Inventory skew
        assert config.skew_coeff == 0.3
        assert config.imbalance_cutoff == 0.65
        
        # Order book levels
        assert config.levels_per_side == 3
        assert config.level_spacing_coeff == 0.4
        
        # Order management
        assert config.min_time_in_book_ms == 500
        assert config.replace_threshold_bps == 3
    
    def test_validation_min_spread_bps(self):
        """Test validation of min_spread_bps."""
        with pytest.raises(ValueError, match="min_spread_bps must be >= 0"):
            StrategyConfig(min_spread_bps=-1)
    
    def test_validation_max_spread_bps(self):
        """Test validation of max_spread_bps."""
        with pytest.raises(ValueError, match="max_spread_bps must be > min_spread_bps"):
            StrategyConfig(min_spread_bps=5, max_spread_bps=3)
    
    def test_validation_levels_per_side(self):
        """Test validation of levels_per_side."""
        with pytest.raises(ValueError, match="levels_per_side must be between 1 and 10"):
            StrategyConfig(levels_per_side=0)
        with pytest.raises(ValueError, match="levels_per_side must be between 1 and 10"):
            StrategyConfig(levels_per_side=11)
    
    def test_validation_skew_coeff(self):
        """Test validation of skew_coeff."""
        with pytest.raises(ValueError, match="skew_coeff must be between 0 and 1"):
            StrategyConfig(skew_coeff=-0.1)
        with pytest.raises(ValueError, match="skew_coeff must be between 0 and 1"):
            StrategyConfig(skew_coeff=1.1)
    
    def test_validation_imbalance_cutoff(self):
        """Test validation of imbalance_cutoff."""
        with pytest.raises(ValueError, match="imbalance_cutoff must be between 0.5 and 0.9"):
            StrategyConfig(imbalance_cutoff=0.4)
        with pytest.raises(ValueError, match="imbalance_cutoff must be between 0.5 and 0.9"):
            StrategyConfig(imbalance_cutoff=0.95)


class TestRiskConfig:
    """Test RiskConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = RiskConfig()
        
        # Feature flags
        assert config.enable_kill_switch is True
        
        # Kill switch thresholds
        assert config.drawdown_day_pct == 1.0
        assert config.max_consecutive_losses == 10
        assert config.max_reject_rate == 0.02
        assert config.max_latency_p95_ms == 300
    
    def test_validation_drawdown_day_pct(self):
        """Test validation of drawdown_day_pct."""
        with pytest.raises(ValueError, match="drawdown_day_pct must be between 0.1 and 10.0"):
            RiskConfig(drawdown_day_pct=0.05)
        with pytest.raises(ValueError, match="drawdown_day_pct must be between 0.1 and 10.0"):
            RiskConfig(drawdown_day_pct=15.0)
    
    def test_validation_max_consecutive_losses(self):
        """Test validation of max_consecutive_losses."""
        with pytest.raises(ValueError, match="max_consecutive_losses must be between 1 and 100"):
            RiskConfig(max_consecutive_losses=0)
        with pytest.raises(ValueError, match="max_consecutive_losses must be between 1 and 100"):
            RiskConfig(max_consecutive_losses=101)
    
    def test_validation_max_reject_rate(self):
        """Test validation of max_reject_rate."""
        with pytest.raises(ValueError, match="max_reject_rate must be between 0.001 and 0.1"):
            RiskConfig(max_reject_rate=0.0005)
        with pytest.raises(ValueError, match="max_reject_rate must be between 0.001 and 0.1"):
            RiskConfig(max_reject_rate=0.15)
    
    def test_validation_max_latency_p95_ms(self):
        """Test validation of max_latency_p95_ms."""
        with pytest.raises(ValueError, match="max_latency_p95_ms must be between 50 and 1000"):
            RiskConfig(max_latency_p95_ms=25)
        with pytest.raises(ValueError, match="max_latency_p95_ms must be between 50 and 1000"):
            RiskConfig(max_latency_p95_ms=1500)


class TestLimitsConfig:
    """Test LimitsConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = LimitsConfig()
        
        assert config.max_active_per_side == 3
        assert config.max_create_per_sec == 4.0
        assert config.max_cancel_per_sec == 4.0
    
    def test_validation_max_active_per_side(self):
        """Test validation of max_active_per_side."""
        with pytest.raises(ValueError, match="max_active_per_side must be between 1 and 20"):
            LimitsConfig(max_active_per_side=0)
        with pytest.raises(ValueError, match="max_active_per_side must be between 1 and 20"):
            LimitsConfig(max_active_per_side=25)
    
    def test_validation_max_create_per_sec(self):
        """Test validation of max_create_per_sec."""
        with pytest.raises(ValueError, match="max_create_per_sec must be between 0.1 and 20.0"):
            LimitsConfig(max_create_per_sec=0.05)
        with pytest.raises(ValueError, match="max_create_per_sec must be between 0.1 and 20.0"):
            LimitsConfig(max_create_per_sec=25.0)
    
    def test_validation_max_cancel_per_sec(self):
        """Test validation of max_cancel_per_sec."""
        with pytest.raises(ValueError, match="max_cancel_per_sec must be between 0.1 and 20.0"):
            LimitsConfig(max_cancel_per_sec=0.05)
        with pytest.raises(ValueError, match="max_cancel_per_sec must be between 0.1 and 20.0"):
            LimitsConfig(max_cancel_per_sec=25.0)


class TestMonitoringConfig:
    """Test MonitoringConfig dataclass."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = MonitoringConfig()
        
        assert config.enable_prometheus is True
        assert config.metrics_port == 8000
        assert config.health_port == 8001
        assert config.log_level == "INFO"
    
    def test_validation_metrics_port(self):
        """Test validation of metrics_port."""
        with pytest.raises(ValueError, match="metrics_port must be between 1024 and 65535"):
            MonitoringConfig(metrics_port=500)
        with pytest.raises(ValueError, match="metrics_port must be between 1024 and 65535"):
            MonitoringConfig(metrics_port=70000)
    
    def test_validation_health_port(self):
        """Test validation of health_port."""
        with pytest.raises(ValueError, match="health_port must be between 1024 and 65535"):
            MonitoringConfig(health_port=500)
        with pytest.raises(ValueError, match="health_port must be between 1024 and 65535"):
            MonitoringConfig(health_port=70000)
    
    def test_validation_log_level(self):
        """Test validation of log_level."""
        with pytest.raises(ValueError, match="log_level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"):
            MonitoringConfig(log_level="INVALID")


class TestConfig:
    """Test main Config class."""
    
    def test_default_configuration(self):
        """Test default configuration creation."""
        config = Config()
        
        # Check that all sub-configs are created
        assert isinstance(config.strategy, StrategyConfig)
        assert isinstance(config.risk, RiskConfig)
        assert isinstance(config.limits, LimitsConfig)
        assert isinstance(config.monitoring, MonitoringConfig)
    
    def test_feature_flags_property(self):
        """Test feature_flags property."""
        config = Config()
        flags = config.feature_flags
        
        assert isinstance(flags, dict)
        assert flags["dynamic_spread"] is True
        assert flags["inventory_skew"] is True
        assert flags["adverse_guard"] is True
        assert flags["kill_switch"] is True
        assert flags["prometheus"] is True
    
    def test_custom_configuration(self):
        """Test custom configuration creation."""
        strategy = StrategyConfig(enable_dynamic_spread=False, min_spread_bps=5)
        risk = RiskConfig(enable_kill_switch=False, drawdown_day_pct=2.0)
        
        config = Config(strategy=strategy, risk=risk)
        
        assert config.strategy.enable_dynamic_spread is False
        assert config.strategy.min_spread_bps == 5
        assert config.risk.enable_kill_switch is False
        assert config.risk.drawdown_day_pct == 2.0


class TestConfigLoader:
    """Test ConfigLoader class."""
    
    def test_load_without_yaml_file(self):
        """Test loading configuration without YAML file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            loader = ConfigLoader(str(Path(temp_dir) / "nonexistent.yaml"))
            config = loader.load()
            
            # Should load with defaults
            assert isinstance(config, AppConfig)
            assert config.strategy.enable_dynamic_spread is True
    
    def test_load_with_yaml_file(self):
        """Test loading configuration with YAML file."""
        yaml_content = """
strategy:
  enable_dynamic_spread: false
  min_spread_bps: 5
  max_spread_bps: 30
  
risk:
  enable_kill_switch: false
  drawdown_day_pct: 2.0
  
limits:
  max_active_per_side: 5
  
monitoring:
  enable_prometheus: false
  metrics_port: 9000
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name
        
        try:
            loader = ConfigLoader(yaml_path)
            config = loader.load()
            
            # Check YAML overrides
            assert config.strategy.enable_dynamic_spread is False
            assert config.strategy.min_spread_bps == 5
            assert config.strategy.max_spread_bps == 30
            assert config.risk.enable_kill_switch is False
            assert config.risk.drawdown_day_pct == 2.0
            assert config.limits.max_active_per_side == 5
            assert config.monitoring.enable_prometheus is False
            assert config.monitoring.metrics_port == 9000
            
        finally:
            os.unlink(yaml_path)
    
    def test_environment_variable_overrides(self):
        """Test environment variable overrides."""
        # Set environment variables
        os.environ['STRATEGY_ENABLE_DYNAMIC_SPREAD'] = 'false'
        os.environ['STRATEGY_MIN_SPREAD_BPS'] = '10'
        os.environ['RISK_ENABLE_KILL_SWITCH'] = 'false'
        os.environ['MONITORING_ENABLE_PROMETHEUS'] = 'false'
        
        try:
            loader = ConfigLoader()
            config = loader.load()
            
            # Check environment variable overrides
            assert config.strategy.enable_dynamic_spread is False
            assert config.strategy.min_spread_bps == 10
            assert config.risk.enable_kill_switch is False
            assert config.monitoring.enable_prometheus is False
            
        finally:
            # Clean up environment variables
            del os.environ['STRATEGY_ENABLE_DYNAMIC_SPREAD']
            del os.environ['STRATEGY_MIN_SPREAD_BPS']
            del os.environ['RISK_ENABLE_KILL_SWITCH']
            del os.environ['MONITORING_ENABLE_PROMETHEUS']
    
    def test_bybit_testnet_override(self):
        """Test Bybit testnet environment variable override."""
        os.environ['BYBIT_USE_TESTNET'] = 'false'
        
        try:
            loader = ConfigLoader()
            config = loader.load()
            
            # Should use mainnet URLs
            assert "testnet" not in config.bybit.rest_url
            assert "testnet" not in config.bybit.ws_url
            
        finally:
            del os.environ['BYBIT_USE_TESTNET']
    
    def test_reload_configuration(self):
        """Test reloading configuration."""
        loader = ConfigLoader()
        config1 = loader.load()
        config2 = loader.reload()
        
        # Should be different instances
        assert config1 is not config2
        assert isinstance(config1, AppConfig)
        assert isinstance(config2, AppConfig)


class TestGlobalConfig:
    """Test global configuration functions."""
    
    def test_get_config_singleton(self):
        """Test that get_config returns singleton."""
        config1 = get_config()
        config2 = get_config()
        
        assert config1 is config2
        assert isinstance(config1, AppConfig)
    
    def test_reload_config_global(self):
        """Test reloading global configuration."""
        config1 = get_config()
        config2 = reload_config()
        
        # Should be different instances
        assert config1 is not config2
        assert isinstance(config1, AppConfig)
        assert isinstance(config2, AppConfig)
        
        # Next get_config should return the new instance
        config3 = get_config()
        assert config3 is config2


class TestConfigValidation:
    """Test configuration validation."""
    
    def test_invalid_yaml_handling(self):
        """Test handling of invalid YAML."""
        invalid_yaml = """
strategy:
  min_spread_bps: -5  # Invalid negative value
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(invalid_yaml)
            yaml_path = f.name
        
        try:
            loader = ConfigLoader(yaml_path)
            
            # Should raise validation error
            with pytest.raises(ValueError, match="min_spread_bps must be >= 0"):
                loader.load()
                
        finally:
            os.unlink(yaml_path)
    
    def test_missing_required_fields(self):
        """Test handling of missing required fields."""
        # StrategyConfig should handle missing fields with defaults
        config = StrategyConfig()
        assert config.enable_dynamic_spread is True
        assert config.min_spread_bps == 2


if __name__ == "__main__":
    pytest.main([__file__])

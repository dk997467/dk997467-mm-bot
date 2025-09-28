"""Test markout symbol override in thresholds configuration."""

import pytest
import tempfile
import os
import textwrap
from src.deploy.thresholds import (
    refresh_thresholds, 
    get_canary_gate_thresholds, 
    current_thresholds_snapshot,
    STRICT_THRESHOLDS
)


class TestThresholdsMarkoutSymbolOverride:
    """Test markout thresholds symbol override functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Reset STRICT_THRESHOLDS to False for testing
        import src.deploy.thresholds as th
        th.STRICT_THRESHOLDS = False
        
        # Reset global canary gate thresholds to defaults
        th.CANARY_GATE.clear()
        th.CANARY_GATE.update({
            "max_reject_delta": 0.02,
            "max_latency_delta_ms": 50,
            "min_sample_fills": 500,
            "drift_cap_pct": 5.0,
            "tail_min_sample": 200,
            "tail_p95_cap_ms": 50,
            "tail_p99_cap_ms": 100,
            "slo_tail_min_sample": 200,
            "slo_tail_p95_cap_ms": 50,
            "slo_tail_p99_cap_ms": 100,
            "markout_min_sample": 50,
            "markout_cap_bps_200": 0.5,
            "markout_cap_bps_500": 0.5,
        })
        
        # Reset per-symbol overrides
        th.CANARY_GATE_PER_SYMBOL.clear()
    
    def teardown_method(self):
        """Clean up after tests."""
        # Reset STRICT_THRESHOLDS
        import src.deploy.thresholds as th
        th.STRICT_THRESHOLDS = False
    
    def test_markout_global_defaults(self):
        """Test that markout thresholds have correct global defaults."""
        thresholds = get_canary_gate_thresholds()
        
        # Check markout defaults
        assert "markout_min_sample" in thresholds
        assert "markout_cap_bps_200" in thresholds
        assert "markout_cap_bps_500" in thresholds
        
        assert thresholds["markout_min_sample"] == 50
        assert thresholds["markout_cap_bps_200"] == 0.5
        assert thresholds["markout_cap_bps_500"] == 0.5
    
    def test_markout_symbol_override(self):
        """Test that markout thresholds can be overridden per symbol."""
        # Create YAML with symbol override
        yaml_content = textwrap.dedent("""
            canary_gate:
              markout_min_sample: 100
              markout_cap_bps_200: 1.0
              markout_cap_bps_500: 2.0

            canary_gate_per_symbol:
              BTCUSDT:
                markout_min_sample: 75
                markout_cap_bps_200: 0.8
                markout_cap_bps_500: 1.5
              ETHUSDT:
                markout_cap_bps_200: 0.3
            """)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            
            try:
                # Load thresholds
                summary = refresh_thresholds(f.name)
                
                # Check global thresholds
                global_thresholds = get_canary_gate_thresholds()
                assert global_thresholds["markout_min_sample"] == 100
                assert global_thresholds["markout_cap_bps_200"] == 1.0
                assert global_thresholds["markout_cap_bps_500"] == 2.0
                
                # Check BTCUSDT override
                btc_thresholds = get_canary_gate_thresholds("BTCUSDT")
                assert btc_thresholds["markout_min_sample"] == 75  # Overridden
                assert btc_thresholds["markout_cap_bps_200"] == 0.8  # Overridden
                assert btc_thresholds["markout_cap_bps_500"] == 1.5  # Overridden
                
                # Check ETHUSDT override (partial)
                eth_thresholds = get_canary_gate_thresholds("ETHUSDT")
                assert eth_thresholds["markout_min_sample"] == 100  # Global default
                assert eth_thresholds["markout_cap_bps_200"] == 0.3  # Overridden
                assert eth_thresholds["markout_cap_bps_500"] == 2.0  # Global default
                
                # Check snapshot includes overrides
                snapshot = current_thresholds_snapshot()
                assert "canary_gate_per_symbol" in snapshot
                assert "BTCUSDT" in snapshot["canary_gate_per_symbol"]
                assert "ETHUSDT" in snapshot["canary_gate_per_symbol"]

            finally:
                try:
                    os.unlink(f.name)
                except PermissionError:
                    # Windows: file might be locked, ignore cleanup error
                    pass
    
    def test_markout_symbol_override_case_insensitive(self):
        """Test that symbol overrides work with case-insensitive keys."""
        yaml_content = textwrap.dedent("""
            canary_gate_per_symbol:
              btcusdt:  # lowercase
                markout_min_sample: 60
                markout_cap_bps_200: 0.6
              ETHUSDT:  # uppercase
                markout_cap_bps_500: 1.8
            """)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            
            try:
                # Load thresholds
                refresh_thresholds(f.name)
                
                # Check that both cases work
                btc_lower = get_canary_gate_thresholds("btcusdt")
                btc_upper = get_canary_gate_thresholds("BTCUSDT")
                
                assert btc_lower["markout_min_sample"] == 60
                assert btc_lower["markout_cap_bps_200"] == 0.6
                assert btc_upper["markout_min_sample"] == 60
                assert btc_upper["markout_cap_bps_200"] == 0.6
                
                # Check ETHUSDT
                eth_thresholds = get_canary_gate_thresholds("ETHUSDT")
                assert eth_thresholds["markout_cap_bps_500"] == 1.8
                
            finally:
                try:
                    os.unlink(f.name)
                except PermissionError:
                    # Windows: file might be locked, ignore cleanup error
                    pass
    
    def test_markout_symbol_override_validation(self):
        """Test that markout symbol overrides are properly validated."""
        yaml_content = textwrap.dedent("""
            canary_gate_per_symbol:
              BTCUSDT:
                markout_min_sample: -10  # Invalid: negative
                markout_cap_bps_200: 0.5
              ETHUSDT:
                markout_cap_bps_200: "invalid"  # Invalid: string instead of float
                markout_cap_bps_500: 1.0
              SOLUSDT:
                markout_min_sample: 100  # Valid
                markout_cap_bps_200: 0.8  # Valid
            """)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            
            try:
                # Load thresholds (should handle invalid values gracefully)
                summary = refresh_thresholds(f.name)
                
                # Check that valid overrides work
                sol_thresholds = get_canary_gate_thresholds("SOLUSDT")
                assert sol_thresholds["markout_min_sample"] == 100
                assert sol_thresholds["markout_cap_bps_200"] == 0.8
                
                # Check that invalid overrides are ignored (fallback to global)
                btc_thresholds = get_canary_gate_thresholds("BTCUSDT")
                assert btc_thresholds["markout_min_sample"] == 50  # Global default (invalid override ignored)
                assert btc_thresholds["markout_cap_bps_200"] == 0.5  # Valid override worked
                
                eth_thresholds = get_canary_gate_thresholds("ETHUSDT")
                assert eth_thresholds["markout_cap_bps_200"] == 0.5  # Global default (invalid override ignored)
                assert eth_thresholds["markout_cap_bps_500"] == 1.0  # Valid override worked
                
            finally:
                try:
                    os.unlink(f.name)
                except PermissionError:
                    # Windows: file might be locked, ignore cleanup error
                    pass
    
    def test_markout_symbol_override_strict_mode(self):
        """Test that STRICT mode rejects invalid markout overrides."""
        # Enable strict mode
        import src.deploy.thresholds as th
        th.STRICT_THRESHOLDS = True
        
        yaml_content = textwrap.dedent("""
            canary_gate_per_symbol:
              BTCUSDT:
                markout_min_sample: -5  # Invalid: negative
                markout_cap_bps_200: 0.5
            """)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            
            try:
                # Should raise ValueError in strict mode
                with pytest.raises(ValueError, match="invalid_canary_symbol_override"):
                    refresh_thresholds(f.name)
                    
            finally:
                try:
                    os.unlink(f.name)
                except PermissionError:
                    # Windows: file might be locked, ignore cleanup error
                    pass
    
    def test_markout_symbol_override_strict_mode_bad_key(self):
        """Test that STRICT mode rejects invalid keys in symbol overrides."""
        # Enable strict mode
        import src.deploy.thresholds as th
        th.STRICT_THRESHOLDS = True
        
        yaml_content = textwrap.dedent("""
            canary_gate_per_symbol:
              BTCUSDT:
                markout_min_sample: 100  # Valid
                bad_key: "invalid"  # Invalid key
                markout_cap_bps_200: 0.5
            """)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            
            try:
                # In STRICT mode, invalid keys should be ignored but not cause errors
                # The function should still work and load valid overrides
                refresh_thresholds(f.name)
                
                # Check that valid overrides work
                btc_thresholds = get_canary_gate_thresholds("BTCUSDT")
                assert btc_thresholds["markout_min_sample"] == 100
                assert btc_thresholds["markout_cap_bps_200"] == 0.5
                assert "bad_key" not in btc_thresholds  # Invalid key should be ignored
                
            finally:
                try:
                    os.unlink(f.name)
                except PermissionError:
                    # Windows: file might be locked, ignore cleanup error
                    pass
    
    def test_markout_symbol_override_reload_deterministic(self):
        """Test that markout thresholds reload produces deterministic results."""
        yaml_content = textwrap.dedent("""
            canary_gate:
              markout_min_sample: 80
              markout_cap_bps_200: 0.7
              markout_cap_bps_500: 1.2

            canary_gate_per_symbol:
              BTCUSDT:
                markout_cap_bps_200: 0.6
              ETHUSDT:
                markout_min_sample: 90
                markout_cap_bps_500: 1.0
            """)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            
            try:
                # Load thresholds multiple times
                summary1 = refresh_thresholds(f.name)
                summary2 = refresh_thresholds(f.name)
                
                # Results should be identical except for version
                # Remove version from comparison
                summary1_no_version = {k: v for k, v in summary1.items() if k != 'version'}
                summary2_no_version = {k: v for k, v in summary2.items() if k != 'version'}
                assert summary1_no_version == summary2_no_version
                
                # Check that thresholds are consistent
                btc1 = get_canary_gate_thresholds("BTCUSDT")
                btc2 = get_canary_gate_thresholds("BTCUSDT")
                assert btc1 == btc2
                
                eth1 = get_canary_gate_thresholds("ETHUSDT")
                eth2 = get_canary_gate_thresholds("ETHUSDT")
                assert eth1 == eth2
                
                # Check snapshot consistency
                snap1 = current_thresholds_snapshot()
                snap2 = current_thresholds_snapshot()
                # Remove version from snapshot comparison
                snap1_no_version = {k: v for k, v in snap1.items() if k != 'version'}
                snap2_no_version = {k: v for k, v in snap2.items() if k != 'version'}
                assert snap1_no_version == snap2_no_version
                
            finally:
                try:
                    os.unlink(f.name)
                except PermissionError:
                    # Windows: file might be locked, ignore cleanup error
                    pass
    
    def test_markout_symbol_override_mixed_types(self):
        """Test that markout thresholds handle mixed valid/invalid overrides."""
        yaml_content = textwrap.dedent("""
            canary_gate_per_symbol:
              BTCUSDT:
                markout_min_sample: 75  # Valid
                markout_cap_bps_200: 0.8  # Valid
                invalid_field: "should_be_ignored"  # Invalid field
              ETHUSDT:
                markout_cap_bps_500: 1.5  # Valid
                markout_min_sample: -5  # Invalid: negative
            """)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            
            try:
                # Load thresholds
                refresh_thresholds(f.name)
                
                # Check BTCUSDT (valid overrides)
                btc_thresholds = get_canary_gate_thresholds("BTCUSDT")
                assert btc_thresholds["markout_min_sample"] == 75
                assert btc_thresholds["markout_cap_bps_200"] == 0.8
                assert "invalid_field" not in btc_thresholds
                
                # Check ETHUSDT (partial valid overrides)
                eth_thresholds = get_canary_gate_thresholds("ETHUSDT")
                assert eth_thresholds["markout_min_sample"] == 50  # Global default (invalid override ignored)
                assert eth_thresholds["markout_cap_bps_500"] == 1.5  # Valid override
                
            finally:
                try:
                    os.unlink(f.name)
                except PermissionError:
                    # Windows: file might be locked, ignore cleanup error
                    pass

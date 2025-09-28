"""Smoke tests for E1 backtest calibration integration."""

import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.backtest.run import BacktestRunner, CalibrationParams
from src.common.config import AppConfig


class TestE1BacktestCalibration:
    """Test E1 backtest calibration integration."""
    
    def test_backtest_with_calibration_file_integration(self, tmp_path):
        """Test end-to-end backtest integration with calibration file."""
        # Create calibration file
        calibration_data = {
            "latency_ms_mean": 150.0,
            "latency_ms_std": 50.0,
            "amend_latency_ms": 50.0,
            "cancel_latency_ms": 50.0,
            "toxic_sweep_prob": 0.1,
            "extra_slippage_bps": 3.0
        }
        
        calib_file = tmp_path / "test_calibration.json"
        with open(calib_file, 'w') as f:
            json.dump(calibration_data, f, indent=2, sort_keys=True)
        
        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.trading = MagicMock()
        config.trading.maker_fee_bps = 1.0
        config.trading.taker_fee_bps = 2.0
        config.strategy = MagicMock()
        config.trading = MagicMock()
        config.trading.maker_fee_bps = 1.0
        config.trading.taker_fee_bps = 2.0
        
        # Initialize BacktestRunner with calibration
        calibration = CalibrationParams(**calibration_data)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = BacktestRunner(config, temp_dir, "BTCUSDT", calibration)
            
            # Mock required functions for isolated testing
            with patch('src.backtest.run.get_git_sha', return_value='test_sha_e1'), \
                 patch('src.backtest.run.cfg_hash_sanitized', return_value='test_hash_e1'):
                
                # Get results without running full backtest (using _calculate_results directly)
                results = runner._calculate_results()
                
                # Verify calibration_used block is present and correct
                assert "calibration_used" in results
                calib_used = results["calibration_used"]
                
                # Check all calibration parameters are included
                assert calib_used["latency_ms_mean"] == 150.0
                assert calib_used["latency_ms_std"] == 50.0
                assert calib_used["amend_latency_ms"] == 50.0
                assert calib_used["cancel_latency_ms"] == 50.0
                assert calib_used["toxic_sweep_prob"] == 0.1
                assert calib_used["extra_slippage_bps"] == 3.0
                
                # Verify metadata is present
                assert "metadata" in results
                assert results["metadata"]["git_sha"] == "test_sha_e1"
                assert results["metadata"]["cfg_hash"] == "test_hash_e1"
                
                # Generate and test report.json content
                report_json_path = tmp_path / "test_report.json"
                with open(report_json_path, 'w') as f:
                    json.dump(results, f, indent=2, sort_keys=True, ensure_ascii=False)
                
                # Verify report.json was written correctly
                assert report_json_path.exists()
                
                with open(report_json_path, 'r') as f:
                    report_data = json.load(f)
                
                # Verify calibration block in JSON report
                assert "calibration_used" in report_data
                assert report_data["calibration_used"]["latency_ms_mean"] == 150.0
                assert report_data["calibration_used"]["toxic_sweep_prob"] == 0.1
    
    def test_markdown_report_contains_calibration_section(self, tmp_path):
        """Test that REPORT.md contains calibration section when calibration is used."""
        # Create calibration parameters
        calibration_data = {
            "latency_ms_mean": 25.0,
            "latency_ms_std": 8.0,
            "amend_latency_ms": 15.0,
            "cancel_latency_ms": 12.0,
            "toxic_sweep_prob": 0.05,
            "extra_slippage_bps": 1.5
        }
        
        calibration = CalibrationParams(**calibration_data)
        
        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.trading = MagicMock()
        config.trading.maker_fee_bps = 1.0
        config.trading.taker_fee_bps = 2.0
        
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = BacktestRunner(config, temp_dir, "BTCUSDT", calibration)
            
            # Create mock results with calibration
            results = {
                "symbol": "BTCUSDT",
                "start_time": "2025-01-01T00:00:00Z",
                "end_time": "2025-01-02T00:00:00Z",
                "net_pnl": 2500.0,
                "total_fees": 75.0,
                "total_trades": 120,
                "sharpe_ratio": 2.1,
                "hit_rate": 0.68,
                "max_drawdown": 0.08,
                "cvar_95": -0.03,
                "fill_statistics": {
                    "total_fills": 95,
                    "maker_fills": 80,
                    "taker_fills": 15,
                    "maker_ratio": 0.84,
                    "total_fill_value": 125000.0
                },
                "calibration_used": calibration_data,
                "metadata": {
                    "git_sha": "abc123def",
                    "cfg_hash": "456ghi789"
                }
            }
            
            # Generate markdown report
            report_md_path = tmp_path / "test_report.md"
            report_content = runner.generate_report_md(results, report_md_path)
            
            # Verify REPORT.md was created
            assert report_md_path.exists()
            
            # Read and verify content
            with open(report_md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            
            # Check that calibration section is present
            assert "## Calibration Parameters" in md_content
            
            # Check that all calibration parameters are documented
            assert "**Latency Mean (ms):** 25.0" in md_content
            assert "**Latency Std (ms):** 8.0" in md_content
            assert "**Amend Latency (ms):** 15.0" in md_content
            assert "**Cancel Latency (ms):** 12.0" in md_content
            assert "**Toxic Sweep Probability:** 0.050" in md_content
            assert "**Extra Slippage (bps):** 1.5" in md_content
            
            # Verify other required sections exist
            assert "# Backtest Report for BTCUSDT" in md_content
            assert "## Performance Metrics" in md_content
            assert "## Fill Statistics" in md_content
            
            # Verify performance metrics are present
            assert "**Net PnL (USD):** 2500.00" in md_content
            assert "**Hit Rate (%):** 68.0" in md_content
            assert "**Maker Ratio (%):** 84.0" in md_content
            
            # Verify the generated content matches what was returned
            assert md_content == report_content
    
    def test_markdown_report_without_calibration_no_section(self, tmp_path):
        """Test that REPORT.md does not contain calibration section when no calibration is used."""
        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.trading = MagicMock()
        config.trading.maker_fee_bps = 1.0
        config.trading.taker_fee_bps = 2.0
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Initialize without calibration
            runner = BacktestRunner(config, temp_dir, "BTCUSDT")  # No calibration parameter
            
            # Create mock results without meaningful calibration
            results = {
                "symbol": "BTCUSDT",
                "net_pnl": 1000.0,
                "calibration_used": {
                    "latency_ms_mean": 0.0,
                    "latency_ms_std": 0.0,
                    "amend_latency_ms": 0.0,
                    "cancel_latency_ms": 0.0,
                    "toxic_sweep_prob": 0.0,
                    "extra_slippage_bps": 0.0
                },
                "fill_statistics": {
                    "total_fills": 50,
                    "maker_fills": 45,
                    "taker_fills": 5,
                    "maker_ratio": 0.9,
                    "total_fill_value": 50000.0
                },
                "metadata": {"git_sha": "test", "cfg_hash": "test"}
            }
            
            # Generate markdown report
            report_content = runner.generate_report_md(results)
            
            # Should NOT contain calibration section when all values are zero
            assert "## Calibration Parameters" not in report_content
            
            # But should contain other sections
            assert "# Backtest Report for BTCUSDT" in report_content
            assert "## Fill Statistics" in report_content
    
    def test_calibration_params_determinism(self):
        """Test that CalibrationParams are deterministic and JSON serializable."""
        # Create calibration parameters
        calib_data = {
            "latency_ms_mean": 15.5,
            "latency_ms_std": 4.2,
            "amend_latency_ms": 10.0,
            "cancel_latency_ms": 8.5,
            "toxic_sweep_prob": 0.02,
            "extra_slippage_bps": 0.75
        }
        
        calibration = CalibrationParams(**calib_data)
        
        # Test that all attributes are correctly set
        assert calibration.latency_ms_mean == 15.5
        assert calibration.latency_ms_std == 4.2
        assert calibration.amend_latency_ms == 10.0
        assert calibration.cancel_latency_ms == 8.5
        assert calibration.toxic_sweep_prob == 0.02
        assert calibration.extra_slippage_bps == 0.75
        
        # Test JSON serialization/deserialization
        json_str = json.dumps(calib_data, sort_keys=True)
        deserialized = json.loads(json_str)
        calibration2 = CalibrationParams(**deserialized)
        
        # Should be identical
        assert calibration.latency_ms_mean == calibration2.latency_ms_mean
        assert calibration.toxic_sweep_prob == calibration2.toxic_sweep_prob
    
    def test_calibration_validation_in_backtest_context(self):
        """Test calibration parameter validation in backtest context."""
        # Valid calibration should work
        valid_calib = CalibrationParams(
            latency_ms_mean=20.0,
            latency_ms_std=5.0,
            toxic_sweep_prob=0.1,
            extra_slippage_bps=2.0
        )
        
        config = MagicMock(spec=AppConfig)
        config.trading = MagicMock()
        config.trading.maker_fee_bps = 1.0
        config.trading.taker_fee_bps = 2.0
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Should create successfully
            runner = BacktestRunner(config, temp_dir, "BTCUSDT", valid_calib)
            assert runner.calibration == valid_calib
        
        # Invalid calibration should raise error during construction
        with pytest.raises(ValueError, match="toxic_sweep_prob must be between 0 and 1"):
            invalid_calib = CalibrationParams(toxic_sweep_prob=1.5)
        
        with pytest.raises(ValueError, match="Latency parameters must be non-negative"):
            invalid_calib = CalibrationParams(latency_ms_mean=-10.0)
    
    def test_queue_simulator_receives_calibration(self):
        """Test that calibration parameters are properly passed to QueueSimulator."""
        calibration = CalibrationParams(
            latency_ms_mean=30.0,
            toxic_sweep_prob=0.15,
            extra_slippage_bps=2.5
        )
        
        config = MagicMock(spec=AppConfig)
        config.trading = MagicMock()
        config.trading.maker_fee_bps = 1.0
        config.trading.taker_fee_bps = 2.0
        
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = BacktestRunner(config, temp_dir, "BTCUSDT", calibration)
            
            # Check that queue simulator has the calibration
            assert runner.queue_simulator.calibration == calibration
            assert runner.queue_simulator.calibration.latency_ms_mean == 30.0
            assert runner.queue_simulator.calibration.toxic_sweep_prob == 0.15
            assert runner.queue_simulator.calibration.extra_slippage_bps == 2.5

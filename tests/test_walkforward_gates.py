"""Tests for walk-forward tuning gates functionality."""

import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.strategy.tuner import WalkForwardTuner, main


class TestWalkForwardGates:
    """Test that walk-forward tuning gates work correctly."""
    
    def test_gates_pass_with_good_metrics(self, tmp_path):
        """Test that gates pass when metrics are above thresholds."""
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        with patch('src.strategy.tuner.WalkForwardTuner.load_data', return_value=mock_data), \
             patch('src.strategy.tuner.WalkForwardTuner._evaluate_params_split') as mock_eval:
            
            # Mock evaluation to return good metrics
            mock_eval.return_value = {
                "net_pnl": 1000.0,      # Above min_pnl (100)
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.8,        # Above min_hit (0.6)
                "maker_share": 0.8,     # Above min_maker (0.7)
                "sharpe": 1.5,
                "cvar95": -500.0,       # Above -max_cvar (-1000)
                "avg_queue_wait": 2.0,
                "quotes": 100,
                "fills": 50
            }
            
            args = [
                "--walk-forward",
                "--data", str(tmp_path / "data.csv"),
                "--symbol", "TEST",
                "--train-days", "2",
                "--validate-hours", "24",
                "--method", "random",
                "--trials", "5",
                "--seed", "42",
                "--gate-min-hit", "0.6",
                "--gate-min-maker", "0.7",
                "--gate-max-cvar", "1000",
                "--gate-min-pnl", "100"
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                # Should not raise SystemExit since gates pass
                try:
                    main()
                except SystemExit as e:
                    # Should exit with code 0 for success
                    assert e.code == 0
            
            # Check that artifacts were created
            artifacts_dir = Path("artifacts/tuning/TEST")
            assert artifacts_dir.exists()
            assert (artifacts_dir / "champion.json").exists()
    
    def test_gates_fail_with_poor_metrics(self, tmp_path):
        """Test that gates fail when metrics are below thresholds."""
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        with patch('src.strategy.tuner.WalkForwardTuner.load_data', return_value=mock_data), \
             patch('src.strategy.tuner.WalkForwardTuner._evaluate_params_split') as mock_eval:
            
            # Mock evaluation to return poor metrics
            mock_eval.return_value = {
                "net_pnl": 50.0,        # Below min_pnl (100)
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.5,        # Below min_hit (0.6)
                "maker_share": 0.6,     # Below min_maker (0.7)
                "sharpe": 1.5,
                "cvar95": -1200.0,      # Below -max_cvar (-1000)
                "avg_queue_wait": 2.0,
                "quotes": 100,
                "fills": 50
            }
            
            args = [
                "--walk-forward",
                "--data", str(tmp_path / "data.csv"),
                "--symbol", "TEST",
                "--train-days", "2",
                "--validate-hours", "24",
                "--method", "random",
                "--trials", "5",
                "--seed", "42",
                "--gate-min-hit", "0.6",
                "--gate-min-maker", "0.7",
                "--gate-max-cvar", "1000",
                "--gate-min-pnl", "100"
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                # Should raise SystemExit with exit code 2 for gate failure
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 2
                
                # Check that report.json contains gate failure information
                report_path = Path("artifacts/tuning/report.json")
                if report_path.exists():
                    with open(report_path, 'r') as f:
                        report_data = json.load(f)
                    assert report_data["exit_code"] == 2
                    assert report_data["gates"]["passed"] == False
                    assert len(report_data["gates"]["reasons"]) > 0
    
    def test_gates_fail_with_specific_reasons(self, tmp_path, capsys):
        """Test that gates provide specific failure reasons."""
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        with patch('src.strategy.tuner.WalkForwardTuner.load_data', return_value=mock_data), \
             patch('src.strategy.tuner.WalkForwardTuner._evaluate_params_split') as mock_eval:
            
            # Mock evaluation to return poor metrics
            mock_eval.return_value = {
                "net_pnl": 50.0,        # Below min_pnl (100)
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.5,        # Below min_hit (0.6)
                "maker_share": 0.6,     # Below min_maker (0.7)
                "sharpe": 1.5,
                "cvar95": -1200.0,      # Below -max_cvar (-1000)
                "avg_queue_wait": 2.0,
                "quotes": 100,
                "fills": 50
            }
            
            args = [
                "--walk-forward",
                "--data", str(tmp_path / "data.csv"),
                "--symbol", "TEST",
                "--train-days", "2",
                "--validate-hours", "24",
                "--method", "random",
                "--trials", "5",
                "--seed", "42",
                "--gate-min-hit", "0.6",
                "--gate-min-maker", "0.7",
                "--gate-max-cvar", "1000",
                "--gate-min-pnl", "100"
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                try:
                    main()
                except SystemExit as e:
                    # Should exit with code 2 for gate failure
                    assert e.code == 2
            
            # Check that failure reasons were printed
            captured = capsys.readouterr()
            output = captured.out + captured.err
            
            # Should contain failure reasons with updated format
            assert "❌ GATES FAILED:" in output
            assert "Hit rate: 0.500 < 0.600" in output
            assert "Maker share: 0.600 < 0.700" in output
            assert "CVaR95: -1200.000 < -1000.000" in output
            assert "NetPnL: 50.000 < 100.000" in output
            assert "Exiting with code 2" in output
    
    def test_gates_with_custom_thresholds(self, tmp_path):
        """Test that gates work with custom threshold values."""
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        with patch('src.strategy.tuner.WalkForwardTuner.load_data', return_value=mock_data), \
             patch('src.strategy.tuner.WalkForwardTuner._evaluate_params_split') as mock_eval:
            
            # Mock evaluation to return borderline metrics
            mock_eval.return_value = {
                "net_pnl": 150.0,       # Above custom min_pnl (100)
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.65,       # Above custom min_hit (0.6)
                "maker_share": 0.75,    # Above custom min_maker (0.7)
                "sharpe": 1.5,
                "cvar95": -800.0,       # Above custom -max_cvar (-1000)
                "avg_queue_wait": 2.0,
                "quotes": 100,
                "fills": 50
            }
            
            args = [
                "--walk-forward",
                "--data", str(tmp_path / "data.csv"),
                "--symbol", "TEST",
                "--train-days", "2",
                "--validate-hours", "24",
                "--method", "random",
                "--trials", "5",
                "--seed", "42",
                "--gate-min-hit", "0.6",
                "--gate-min-maker", "0.7",
                "--gate-max-cvar", "1000",
                "--gate-min-pnl", "100"
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                # Should pass with these thresholds
                try:
                    main()
                except SystemExit as e:
                    assert e.code == 0  # Should pass
            
            # Check that artifacts were created
            artifacts_dir = Path("artifacts/tuning/TEST")
            assert artifacts_dir.exists()
    
    def test_gates_with_extreme_thresholds(self, tmp_path):
        """Test that gates work with extreme threshold values."""
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        with patch('src.strategy.tuner.WalkForwardTuner.load_data', return_value=mock_data), \
             patch('src.strategy.tuner.WalkForwardTuner._evaluate_params_split') as mock_eval:
            
            # Mock evaluation to return extreme metrics
            mock_eval.return_value = {
                "net_pnl": 10000.0,     # Very high
                "maker_rebate": 100.0,
                "taker_fees": 200.0,
                "hit_rate": 0.99,       # Very high
                "maker_share": 0.99,    # Very high
                "sharpe": 5.0,
                "cvar95": -50.0,        # Very low (good)
                "avg_queue_wait": 0.1,
                "quotes": 1000,
                "fills": 500
            }
            
            args = [
                "--walk-forward",
                "--data", str(tmp_path / "data.csv"),
                "--symbol", "TEST",
                "--train-days", "2",
                "--validate-hours", "24",
                "--method", "random",
                "--trials", "5",
                "--seed", "42",
                "--gate-min-hit", "0.95",      # Very high threshold
                "--gate-min-maker", "0.95",    # Very high threshold
                "--gate-max-cvar", "100",      # Very low threshold
                "--gate-min-pnl", "5000"      # Very high threshold
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                # Should pass with these extreme thresholds
                try:
                    main()
                except SystemExit as e:
                    assert e.code == 0  # Should pass
            
            # Check that artifacts were created
            artifacts_dir = Path("artifacts/tuner/TEST")
            assert artifacts_dir.exists()
    
    def test_cleanup(self):
        """Clean up test artifacts."""
        import shutil
        if Path("artifacts").exists():
            shutil.rmtree("artifacts")

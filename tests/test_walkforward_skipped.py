"""Tests for walk-forward tuning skipped splits functionality."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.strategy.tuner import WalkForwardTuner, main


class TestWalkForwardSkipped:
    """Test that walk-forward tuning correctly handles skipped splits."""
    
    def test_skipped_splits_excluded_from_aggregates(self, tmp_path):
        """Test that skipped splits are excluded from champion selection."""
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        with patch('src.strategy.tuner.WalkForwardTuner.load_data', return_value=mock_data), \
             patch('src.strategy.tuner.WalkForwardTuner._evaluate_params_split') as mock_eval:
            
            # Mock evaluation to return metrics with very few fills (will be skipped)
            mock_eval.return_value = {
                "net_pnl": 1000.0,
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.8,
                "maker_share": 0.8,
                "sharpe": 1.5,
                "cvar95": -500.0,
                "avg_queue_wait": 2.0,
                "quotes": 100,
                "fills": 0  # This will cause skipping due to min_fills=1
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
                "--min-fills", "1"  # Skip splits with < 1 fill
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                try:
                    main()
                except SystemExit as e:
                    # Should exit with code 1 since no valid splits were found
                    assert e.code == 1
            
            # Check that report.json contains skipped splits information
            report_path = Path("artifacts/tuning/report.json")
            assert report_path.exists()
            
            with open(report_path, 'r') as f:
                report_data = json.load(f)
            
            # Should have skipped splits recorded
            assert "skipped_splits" in report_data
            skipped_splits = report_data["skipped_splits"]
            assert len(skipped_splits) > 0
            
            # Each skipped split should have split_id and reason
            for skipped in skipped_splits:
                assert "split_id" in skipped
                assert "reason" in skipped
                assert "Too few fills" in skipped["reason"]
    
    def test_tiny_validation_window_skipped(self, tmp_path):
        """Test that splits with tiny validation windows are skipped."""
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        with patch('src.strategy.tuner.WalkForwardTuner.load_data', return_value=mock_data), \
             patch('src.strategy.tuner.WalkForwardTuner._evaluate_params_split') as mock_eval:
            
            # Mock evaluation to return good metrics
            mock_eval.return_value = {
                "net_pnl": 1000.0,
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.8,
                "maker_share": 0.8,
                "sharpe": 1.5,
                "cvar95": -500.0,
                "avg_queue_wait": 2.0,
                "quotes": 100,
                "fills": 50
            }
            
            args = [
                "--walk-forward",
                "--data", str(tmp_path / "data.csv"),
                "--symbol", "TEST",
                "--train-days", "2",
                "--validate-hours", "1",  # Very short validation window
                "--method", "random",
                "--trials", "5",
                "--seed", "42",
                "--min-val-minutes", "120"  # Require at least 2 hours (120 minutes)
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                try:
                    main()
                except SystemExit as e:
                    # Should exit with code 1 since no valid splits were found
                    assert e.code == 1
            
            # Check that report.json contains skipped splits due to short validation
            report_path = Path("artifacts/tuning/report.json")
            assert report_path.exists()
            
            with open(report_path, 'r') as f:
                report_data = json.load(f)
            
            # Should have skipped splits recorded
            assert "skipped_splits" in report_data
            skipped_splits = report_data["skipped_splits"]
            assert len(skipped_splits) > 0
            
            # Should contain reason about validation window being too short
            found_short_window = False
            for skipped in skipped_splits:
                if "Validation window too short" in skipped["reason"]:
                    found_short_window = True
                    break
            assert found_short_window, "Expected to find skipped splits due to short validation window"
    
    def test_skipped_splits_in_report_md(self, tmp_path):
        """Test that REPORT.md contains a section for skipped splits."""
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        with patch('src.strategy.tuner.WalkForwardTuner.load_data', return_value=mock_data), \
             patch('src.strategy.tuner.WalkForwardTuner._evaluate_params_split') as mock_eval:
            
            # Mock evaluation to return metrics with zero fills (will be skipped)
            mock_eval.return_value = {
                "net_pnl": 1000.0,
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.8,
                "maker_share": 0.8,
                "sharpe": 1.5,
                "cvar95": -500.0,
                "avg_queue_wait": 2.0,
                "quotes": 100,
                "fills": 0  # Will cause skipping
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
                "--min-fills", "1"
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                try:
                    main()
                except SystemExit as e:
                    # Should exit with code 1 (internal error) when all splits are skipped
                    assert e.code == 1
            
            # Check REPORT.md contains skipped splits section
            report_md_path = Path("artifacts/tuning/REPORT.md")
            assert report_md_path.exists()
            
            with open(report_md_path, 'r', encoding='utf-8') as f:
                report_content = f.read()
            
            # Should have skipped splits section
            assert "## Skipped Splits" in report_content
            assert "Too few fills" in report_content
            
            # Should show counts in summary
            assert "(Used:" in report_content
            assert "Skipped:" in report_content

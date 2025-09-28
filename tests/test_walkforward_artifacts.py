"""Tests for walk-forward tuning artifacts generation."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.strategy.tuner import WalkForwardTuner, main


class TestWalkForwardArtifacts:
    """Test that walk-forward tuning generates all required artifacts."""
    
    def test_artifacts_directory_structure(self, tmp_path):
        """Test that artifacts are created in the correct directory structure."""
        # Mock data and parameters
        import polars as pl
        from datetime import datetime, timedelta, timezone
        
        # Create realistic mock data with timestamp column
        start_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2025, 12, 31, tzinfo=timezone.utc)
        
        # Generate timestamps every hour
        timestamps = []
        current = start_time
        while current <= end_time:
            timestamps.append(current)
            current += timedelta(hours=1)
        
        # Create mock DataFrame
        mock_data = pl.DataFrame({
            "timestamp": timestamps,
            "symbol": ["TEST"] * len(timestamps),
            "price": [150.0] * len(timestamps),
            "volume": [5000.0] * len(timestamps)
        })
        
        # Mock the entire WalkForwardTuner class methods
        with patch.object(WalkForwardTuner, 'load_data', return_value=mock_data), \
             patch.object(WalkForwardTuner, '_evaluate_params_split') as mock_eval:
            
            # Mock evaluation to return consistent metrics
            mock_eval.return_value = {
                "net_pnl": 500.0,
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.7,
                "maker_share": 0.8,
                "sharpe": 1.5,
                "cvar95": -300.0,
                "avg_queue_wait": 2.0,
                "quotes": 100,
                "fills": 50
            }
            
            # Run walk-forward tuning
            args = [
                "--walk-forward",
                "--data", str(tmp_path / "data.csv"),
                "--symbol", "TEST",
                "--train-days", "2",
                "--validate-hours", "24",
                "--method", "random",
                "--trials", "5",
                "--seed", "42"
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                try:
                    main()
                except SystemExit as e:
                    assert e.code == 0  # Successful exit
            
            # Check directory structure
            artifacts_dir = Path("artifacts/tuning/TEST")
            assert artifacts_dir.exists()
            
            # Check individual split results with zero-padded names
            split_files = list(artifacts_dir.glob("split_*_best.json"))
            assert len(split_files) > 0
            
            # Verify zero-padded naming convention
            zero_pad_files = list(artifacts_dir.glob("split_[0-9][0-9][0-9]_best.json"))
            assert len(zero_pad_files) > 0, "Expected zero-padded split filenames like split_000_best.json"
            
            # Check champion and report files
            assert (artifacts_dir / "champion.json").exists()
            assert (artifacts_dir / "REPORT.md").exists()
            
            # Check for report.json in parent output directory
            report_json_file = Path("artifacts/tuning/report.json")
            assert report_json_file.exists(), "report.json should exist"
    
    def test_split_results_contain_required_fields(self, tmp_path):
        """Test that split results contain all required metadata fields."""
        import polars as pl
        from datetime import datetime, timedelta, timezone
        
        # Create realistic mock data with timestamp column
        start_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2025, 12, 31, tzinfo=timezone.utc)
        
        # Generate timestamps every hour
        timestamps = []
        current = start_time
        while current <= end_time:
            timestamps.append(current)
            current += timedelta(hours=1)
        
        # Create mock DataFrame
        mock_data = pl.DataFrame({
            "timestamp": timestamps,
            "symbol": ["TEST"] * len(timestamps),
            "price": [150.0] * len(timestamps),
            "volume": [5000.0] * len(timestamps)
        })
        
        with patch.object(WalkForwardTuner, 'load_data', return_value=mock_data), \
             patch.object(WalkForwardTuner, '_evaluate_params_split') as mock_eval:
            
            mock_eval.return_value = {
                "net_pnl": 500.0,
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.7,
                "maker_share": 0.8,
                "sharpe": 1.5,
                "cvar95": -300.0,
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
                "--seed", "42"
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                try:
                    main()
                except SystemExit as e:
                    assert e.code == 0  # Successful exit
            
            # Check that split results were created
            artifacts_dir = Path("artifacts/tuning/TEST")
            split_files = list(artifacts_dir.glob("split_*_best.json"))
            assert len(split_files) > 0
            
            # Check first split result
            with open(split_files[0], 'r') as f:
                split_result = json.load(f)
            
            # Check required fields
            assert "split_id" in split_result
            assert "git_sha" in split_result
            assert "cfg_hash" in split_result
            assert "seed" in split_result
            assert "time_bounds" in split_result
            
            # Check time_bounds format (UTC ISO8601 with 'Z')
            time_bounds = split_result["time_bounds"]
            assert "train_from" in time_bounds
            assert "train_to" in time_bounds
            assert "val_from" in time_bounds
            assert "val_to" in time_bounds
            
            # Check that timestamps end with 'Z' (UTC)
            for time_key in ["train_from", "train_to", "val_from", "val_to"]:
                assert time_bounds[time_key].endswith('Z')
    
    def test_champion_json_contains_metadata(self, tmp_path):
        """Test that champion.json contains all required metadata."""
        import polars as pl
        from datetime import datetime, timedelta, timezone
        
        # Create realistic mock data with timestamp column
        start_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2025, 12, 31, tzinfo=timezone.utc)
        
        # Generate timestamps every hour
        timestamps = []
        current = start_time
        while current <= end_time:
            timestamps.append(current)
            current += timedelta(hours=1)
        
        # Create mock DataFrame
        mock_data = pl.DataFrame({
            "timestamp": timestamps,
            "symbol": ["TEST"] * len(timestamps),
            "price": [150.0] * len(timestamps),
            "volume": [5000.0] * len(timestamps)
        })
        
        with patch.object(WalkForwardTuner, 'load_data', return_value=mock_data), \
             patch.object(WalkForwardTuner, '_evaluate_params_split') as mock_eval:
            
            mock_eval.return_value = {
                "net_pnl": 500.0,
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.7,
                "maker_share": 0.8,
                "sharpe": 1.5,
                "cvar95": -300.0,
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
                "--seed", "42"
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                try:
                    main()
                except SystemExit as e:
                    assert e.code == 0  # Successful exit
            
            # Check champion.json
            champion_path = Path("artifacts/tuning/TEST/champion.json")
            assert champion_path.exists()
            
            with open(champion_path, 'r') as f:
                champion_data = json.load(f)
            
            # Check required fields
            assert "git_sha" in champion_data
            assert "cfg_hash" in champion_data
            assert "seed" in champion_data
            assert "champion_params" in champion_data
            assert "champion_metrics" in champion_data
            assert "splits_summary" in champion_data
            
            # Check splits_summary contains time_bounds
            splits_summary = champion_data["splits_summary"]
            assert len(splits_summary) > 0
            
            # Check that first split has time_bounds in UTC ISO8601 format
            first_split = splits_summary[0]
            assert "time_bounds" in first_split
            
            time_bounds = first_split["time_bounds"]
            for time_key in ["train_from", "train_to", "val_from", "val_to"]:
                assert time_bounds[time_key].endswith('Z')
            
            # Check report.json metadata and structure
            report_path = Path("artifacts/tuning/report.json")
            assert report_path.exists()
            
            with open(report_path, 'r') as f:
                report_data = json.load(f)
            
            # Check required report.json fields
            assert "git_sha" in report_data
            assert "cfg_hash" in report_data  
            assert "seed" in report_data
            assert "exit_code" in report_data
            assert "gates" in report_data
            assert "baseline_drift_pct" in report_data
            
            # Check gates structure
            gates = report_data["gates"]
            assert "passed" in gates
            assert "reasons" in gates
            assert "thresholds" in gates
            assert isinstance(gates["passed"], bool)
            assert isinstance(gates["reasons"], list)
    
    def test_report_md_contains_required_sections(self, tmp_path):
        """Test that REPORT.md contains all required sections."""
        import polars as pl
        from datetime import datetime, timedelta, timezone
        
        # Create realistic mock data with timestamp column
        start_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2025, 12, 31, tzinfo=timezone.utc)
        
        # Generate timestamps every hour
        timestamps = []
        current = start_time
        while current <= end_time:
            timestamps.append(current)
            current += timedelta(hours=1)
        
        # Create mock DataFrame
        mock_data = pl.DataFrame({
            "timestamp": timestamps,
            "symbol": ["TEST"] * len(timestamps),
            "price": [150.0] * len(timestamps),
            "volume": [5000.0] * len(timestamps)
        })
        
        with patch.object(WalkForwardTuner, 'load_data', return_value=mock_data), \
             patch.object(WalkForwardTuner, '_evaluate_params_split') as mock_eval:
            
            mock_eval.return_value = {
                "net_pnl": 500.0,
                "maker_rebate": 10.0,
                "taker_fees": 20.0,
                "hit_rate": 0.7,
                "maker_share": 0.8,
                "sharpe": 1.5,
                "cvar95": -300.0,
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
                "--seed", "42"
            ]
            
            with patch('sys.argv', ['tuner.py'] + args):
                try:
                    main()
                except SystemExit as e:
                    assert e.code == 0  # Successful exit
            
            # Check REPORT.md
            report_path = Path("artifacts/tuning/TEST/REPORT.md")
            assert report_path.exists()
            
            with open(report_path, 'r', encoding='utf-8') as f:
                report_content = f.read()
            
            # Check required sections
            assert "# Walk-forward Tuning Report for TEST" in report_content
            assert "## Time Windows" in report_content
            assert "## Champion Parameters" in report_content
            assert "## Champion Metrics" in report_content
            assert "## Gates & Validation" in report_content
            
            # Check time windows table
            assert "| Split | Train From | Train To | Validate From | Validate To |" in report_content
            
            # Check champion parameters in JSON format
            assert "```json" in report_content
            assert "spread_bps" in report_content
    
    def test_cleanup(self):
        """Clean up test artifacts."""
        import shutil
        if Path("artifacts").exists():
            shutil.rmtree("artifacts")

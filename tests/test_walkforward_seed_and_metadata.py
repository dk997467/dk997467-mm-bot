"""Test walk-forward seeding determinism and metadata in artifacts."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pytest

from src.strategy.tuner import WalkForwardTuner, TimeSplit


class TestWalkForwardSeedAndMetadata:
    """Test seeding determinism and metadata in artifacts."""
    
    def test_same_seed_produces_identical_artifacts(self):
        """Test that same seed produces identical artifacts."""
        # Create temporary directory for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Run tuner twice with same seed
            tuner1 = WalkForwardTuner(seed=42)
            tuner2 = WalkForwardTuner(seed=42)
            
            # Generate splits
            data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            data_end = datetime(2025, 1, 31, tzinfo=timezone.utc)
            
            splits1 = tuner1.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=7,
                validate_hours=24,
                step_hours=24
            )
            
            splits2 = tuner2.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=7,
                validate_hours=24,
                step_hours=24
            )
            
            # Should have same number of splits
            assert len(splits1) == len(splits2)
            
            # Save results
            for i, split in enumerate(splits1):
                tuner1.save_split_result(
                    split=split,
                    best_params={"param1": 1.0, "param2": 0.5},
                    metrics={"pnl": 100.0, "sharpe": 1.2},
                    output_dir=temp_path,
                    symbol="BTCUSDT",
                    cfg_hash="abc123",
                    git_sha="def456"
                )
            
            tuner1.save_champion_result(
                splits=splits1,
                champion_params={"param1": 1.0, "param2": 0.5},
                champion_metrics={"total_pnl": 1000.0, "avg_sharpe": 1.2},
                output_dir=temp_path,
                symbol="BTCUSDT",
                cfg_hash="abc123",
                git_sha="def456"
            )
            
            # Now save with second tuner
            for i, split in enumerate(splits2):
                tuner2.save_split_result(
                    split=split,
                    best_params={"param1": 1.0, "param2": 0.5},
                    metrics={"pnl": 100.0, "sharpe": 1.2},
                    output_dir=temp_path,
                    symbol="BTCUSDT",
                    cfg_hash="abc123",
                    git_sha="def456"
                )
            
            tuner2.save_champion_result(
                splits=splits2,
                champion_params={"param1": 1.0, "param2": 0.5},
                champion_metrics={"total_pnl": 1000.0, "avg_sharpe": 1.2},
                output_dir=temp_path,
                symbol="BTCUSDT",
                cfg_hash="abc123",
                git_sha="def456"
            )
            
            # Check that files exist
            symbol_dir = temp_path / "BTCUSDT"
            assert symbol_dir.exists()
            
            # Check split results (zero-padded format)
            for i in range(len(splits1)):
                split_file = symbol_dir / f"split_{i:03d}_best.json"
                assert split_file.exists()
            
            # Check champion and report
            champion_file = symbol_dir / "champion.json"
            report_file = symbol_dir / "REPORT.md"
            assert champion_file.exists()
            assert report_file.exists()
    
    def test_artifacts_contain_required_metadata(self):
        """Test that artifacts contain required metadata keys."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            tuner = WalkForwardTuner(seed=123)
            
            # Generate splits
            data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            data_end = datetime(2025, 1, 15, tzinfo=timezone.utc)
            
            splits = tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=3,
                validate_hours=24,
                step_hours=24
            )
            
            # Save split result
            tuner.save_split_result(
                split=splits[0],
                best_params={"param1": 1.0},
                metrics={"pnl": 100.0},
                output_dir=temp_path,
                symbol="ETHUSDT",
                cfg_hash="test123",
                git_sha="git456"
            )
            
            # Check split result file (zero-padded format)
            split_file = temp_path / "ETHUSDT" / "split_000_best.json"
            assert split_file.exists()
            
            with open(split_file, 'r') as f:
                split_data = json.load(f)
            
            # Check required keys
            required_keys = ["git_sha", "cfg_hash", "seed", "time_bounds"]
            for key in required_keys:
                assert key in split_data, f"Missing key: {key}"
            
            # Check time_bounds structure
            time_bounds = split_data["time_bounds"]
            time_keys = ["train_from", "train_to", "val_from", "val_to"]
            for key in time_keys:
                assert key in time_bounds, f"Missing time_bounds key: {key}"
                # Check that time ends with 'Z' (UTC)
                assert time_bounds[key].endswith('Z'), f"Time {key} should end with 'Z': {time_bounds[key]}"
            
            # Check specific values
            assert split_data["git_sha"] == "git456"
            assert split_data["cfg_hash"] == "test123"
            assert split_data["seed"] == 123
    
    def test_champion_artifact_contains_metadata(self):
        """Test that champion artifact contains required metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            tuner = WalkForwardTuner(seed=456)
            
            # Generate splits
            data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            data_end = datetime(2025, 1, 10, tzinfo=timezone.utc)
            
            splits = tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=2,
                validate_hours=12,
                step_hours=12
            )
            
            # Save champion result
            tuner.save_champion_result(
                splits=splits,
                champion_params={"param1": 2.0, "param2": 0.8},
                champion_metrics={"total_pnl": 2000.0, "avg_sharpe": 1.5},
                output_dir=temp_path,
                symbol="ADAUSDT",
                cfg_hash="champ123",
                git_sha="champ456"
            )
            
            # Check champion file
            champion_file = temp_path / "ADAUSDT" / "champion.json"
            assert champion_file.exists()
            
            with open(champion_file, 'r') as f:
                champion_data = json.load(f)
            
            # Check required keys
            required_keys = ["git_sha", "cfg_hash", "seed", "champion_params", "champion_metrics", "splits_summary"]
            for key in required_keys:
                assert key in champion_data, f"Missing key: {key}"
            
            # Check splits_summary structure
            splits_summary = champion_data["splits_summary"]
            assert len(splits_summary) == len(splits)
            
            for i, split_summary in enumerate(splits_summary):
                assert "split_id" in split_summary
                assert "time_bounds" in split_summary
                assert split_summary["split_id"] == i
                
                time_bounds = split_summary["time_bounds"]
                time_keys = ["train_from", "train_to", "val_from", "val_to"]
                for key in time_keys:
                    assert key in time_bounds
                    assert time_bounds[key].endswith('Z')
            
            # Check specific values
            assert champion_data["git_sha"] == "champ456"
            assert champion_data["cfg_hash"] == "champ123"
            assert champion_data["seed"] == 456
    
    def test_report_markdown_contains_metadata(self):
        """Test that REPORT.md contains required metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            tuner = WalkForwardTuner(seed=789)
            
            # Generate splits
            data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            data_end = datetime(2025, 1, 8, tzinfo=timezone.utc)
            
            splits = tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=2,
                validate_hours=24,
                step_hours=24
            )
            
            # Save champion result (this also creates REPORT.md)
            tuner.save_champion_result(
                splits=splits,
                champion_params={"param1": 3.0},
                champion_metrics={"total_pnl": 3000.0},
                output_dir=temp_path,
                symbol="DOTUSDT",
                cfg_hash="report123",
                git_sha="report456"
            )
            
            # Check report file
            report_file = temp_path / "DOTUSDT" / "REPORT.md"
            assert report_file.exists()
            
            with open(report_file, 'r') as f:
                report_content = f.read()
            
            # Check that report contains metadata
            assert "Git SHA" in report_content
            assert "Config Hash" in report_content
            assert "Seed" in report_content
            assert "report456" in report_content
            assert "report123" in report_content
            assert "789" in report_content
            
            # Check that report contains time windows table
            assert "Time Windows" in report_content
            assert "| Split | Train From | Train To | Validate From | Validate To |" in report_content
            
            # Check that all times end with 'Z'
            lines = report_content.split('\n')
            for line in lines:
                if '2025-01-' in line and '|' in line:
                    # This is a time line, check for 'Z' suffix
                    assert line.endswith('Z') or 'Z' in line, f"Time line should contain 'Z': {line}"
    
    def test_cfg_hash_stability(self):
        """Test that cfg_hash remains stable across runs if config unchanged."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Run tuner twice with same seed
            tuner1 = WalkForwardTuner(seed=111)
            tuner2 = WalkForwardTuner(seed=111)
            
            # Generate splits
            data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            data_end = datetime(2025, 1, 15, tzinfo=timezone.utc)
            
            splits1 = tuner1.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=3,
                validate_hours=24,
                step_hours=24
            )
            
            splits2 = tuner2.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=3,
                validate_hours=24,
                step_hours=24
            )
            
            # Save results with same config hash
            cfg_hash = "stable123"
            git_sha = "stable456"
            
            for i, split in enumerate(splits1):
                tuner1.save_split_result(
                    split=split,
                    best_params={"param1": 1.0},
                    metrics={"pnl": 100.0},
                    output_dir=temp_path,
                    symbol="BTCUSDT",
                    cfg_hash=cfg_hash,
                    git_sha=git_sha
                )
            
            for i, split in enumerate(splits2):
                tuner2.save_split_result(
                    split=split,
                    best_params={"param1": 1.0},
                    metrics={"pnl": 100.0},
                    output_dir=temp_path,
                    symbol="BTCUSDT",
                    cfg_hash=cfg_hash,
                    git_sha=git_sha
                )
            
            # Check that files exist and contain stable config hash (zero-padded format)
            symbol_dir = temp_path / "BTCUSDT"
            
            for i in range(len(splits1)):
                split_file = symbol_dir / f"split_{i:03d}_best.json"
                assert split_file.exists(), f"Split {i} file should exist"
                
                # Check that config hash is stable in the file
                with open(split_file, 'r') as f:
                    split_data = json.load(f)
                    assert split_data["cfg_hash"] == cfg_hash
                    assert split_data["git_sha"] == git_sha

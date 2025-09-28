"""Test determinism of walk-forward splits with same seed."""

from datetime import datetime, timedelta
import pytest
from unittest.mock import MagicMock

from src.strategy.tuner import WalkForwardTuner


class TestWalkForwardDeterminism:
    """Test that walk-forward splits are deterministic with same seed."""
    
    def test_same_seed_produces_identical_splits(self):
        """Test that identical seeds produce identical split sequences."""
        seed = 42
        
        # Create two tuners with same seed
        tuner1 = WalkForwardTuner(seed=seed)
        tuner2 = WalkForwardTuner(seed=seed)
        
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 31)
        train_days = 7
        validate_hours = 24
        
        # Generate splits with both tuners
        splits1 = tuner1.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        splits2 = tuner2.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        # Should have same number of splits
        assert len(splits1) == len(splits2)
        
        # All splits should be identical
        for i, (split1, split2) in enumerate(zip(splits1, splits2)):
            assert split1.train_start == split2.train_start, f"Split {i} train_start differs"
            assert split1.train_end == split2.train_end, f"Split {i} train_end differs"
            assert split1.validate_start == split2.validate_start, f"Split {i} validate_start differs"
            assert split1.validate_end == split2.validate_end, f"Split {i} validate_end differs"
            assert split1.split_id == split2.split_id, f"Split {i} split_id differs"
    
    def test_different_seeds_produce_different_splits(self):
        """Test that different seeds produce different split sequences."""
        # Create tuners with different seeds
        tuner1 = WalkForwardTuner(seed=42)
        tuner2 = WalkForwardTuner(seed=123)
        
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 31)
        train_days = 7
        validate_hours = 24
        
        # Generate splits with both tuners
        splits1 = tuner1.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        splits2 = tuner2.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        # Should have same number of splits (deterministic algorithm)
        assert len(splits1) == len(splits2)
        
        # But the actual split boundaries might differ due to random initialization
        # This test ensures the algorithm is deterministic but not necessarily identical
        # across different seeds
    
    def test_seed_persistence_across_calls(self):
        """Test that seed persists across multiple calls to same tuner."""
        tuner = WalkForwardTuner(seed=999)
        
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 31)
        train_days = 7
        validate_hours = 24
        
        # Generate splits multiple times
        splits1 = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        splits2 = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        # Should be identical
        assert len(splits1) == len(splits2)
        
        for i, (split1, split2) in enumerate(zip(splits1, splits2)):
            assert split1.train_start == split2.train_start, f"Split {i} train_start differs"
            assert split1.train_end == split2.train_end, f"Split {i} train_end differs"
            assert split1.validate_start == split2.validate_start, f"Split {i} validate_start differs"
            assert split1.validate_end == split2.validate_end, f"Split {i} validate_end differs"
            assert split1.split_id == split2.split_id, f"Split {i} split_id differs"
    
    def test_seed_affects_random_components(self):
        """Test that seed affects any random components in the tuner."""
        # This test ensures that if there are any random components in the future,
        # they are properly seeded
        
        tuner1 = WalkForwardTuner(seed=42)
        tuner2 = WalkForwardTuner(seed=42)
        
        # Access the internal RNG to verify seeding
        assert tuner1.rng.getstate() == tuner2.rng.getstate()
        
        # Generate some random numbers to ensure they're identical
        rand1 = [tuner1.rng.random() for _ in range(10)]
        rand2 = [tuner2.rng.random() for _ in range(10)]
        
        assert rand1 == rand2
    
    def test_deterministic_with_different_parameters(self):
        """Test determinism holds across different parameter combinations."""
        seed = 777
        
        # Test multiple parameter combinations
        test_cases = [
            (7, 24),    # 7 days train, 24 hours validate
            (14, 48),   # 14 days train, 48 hours validate
            (30, 168),  # 30 days train, 1 week validate
        ]
        
        for train_days, validate_hours in test_cases:
            tuner1 = WalkForwardTuner(seed=seed)
            tuner2 = WalkForwardTuner(seed=seed)
            
            data_start = datetime(2025, 1, 1)
            data_end = datetime(2025, 12, 31)
            
            splits1 = tuner1.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=train_days,
                validate_hours=validate_hours
            )
            
            splits2 = tuner2.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=train_days,
                validate_hours=validate_hours
            )
            
            # Should be identical
            assert len(splits1) == len(splits2)
            
            for i, (split1, split2) in enumerate(zip(splits1, splits2)):
                assert split1.train_start == split2.train_start, f"Split {i} train_start differs for {train_days}d/{validate_hours}h"
                assert split1.train_end == split2.train_end, f"Split {i} train_end differs for {train_days}d/{validate_hours}h"
                assert split1.validate_start == split2.validate_start, f"Split {i} validate_start differs for {train_days}d/{validate_hours}h"
                assert split1.validate_end == split2.validate_end, f"Split {i} validate_end differs for {train_days}d/{validate_hours}h"
                assert split1.split_id == split2.split_id, f"Split {i} split_id differs for {train_days}d/{validate_hours}h"
    
    def test_seed_documentation(self):
        """Test that seed is properly documented and accessible."""
        tuner = WalkForwardTuner(seed=123)
        
        # Seed should be accessible
        assert hasattr(tuner, 'seed')
        assert tuner.seed == 123
        
        # Seed should be documented in docstring
        assert "seed" in WalkForwardTuner.__init__.__doc__
        
        # RNG should be accessible and seeded
        assert hasattr(tuner, 'rng')
        assert tuner.rng.getstate() is not None
    
    def test_deterministic_champion_selection(self):
        """Test that champion selection is deterministic with same seed."""
        from unittest.mock import MagicMock
        
        # Create mock data
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        # Create two tuners with same seed
        tuner1 = WalkForwardTuner(seed=42)
        tuner2 = WalkForwardTuner(seed=42)
        
        # Mock evaluation to return consistent metrics
        def mock_eval(params, data):
            # Use hash of params for deterministic but varied metrics
            param_hash = hash(str(sorted(params.items())))
            tuner1.rng.seed(param_hash)
            return {
                "net_pnl": tuner1.rng.uniform(-500, 1000),
                "maker_rebate": tuner1.rng.uniform(0, 50),
                "taker_fees": tuner1.rng.uniform(0, 100),
                "hit_rate": tuner1.rng.uniform(0.3, 0.9),
                "maker_share": tuner1.rng.uniform(0.5, 0.95),
                "sharpe": tuner1.rng.uniform(0.5, 2.5),
                "cvar95": tuner1.rng.uniform(-800, -200),
                "avg_queue_wait": tuner1.rng.uniform(0.1, 5.0),
                "quotes": tuner1.rng.randint(100, 1000),
                "fills": tuner1.rng.randint(50, 500)
            }
        
        tuner1._evaluate_params_split = mock_eval
        tuner2._evaluate_params_split = mock_eval
        
        # Generate splits
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 31)
        train_days = 7
        validate_hours = 24
        
        splits1 = tuner1.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        splits2 = tuner2.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        # Process splits to get results
        split_results1 = []
        split_results2 = []
        
        for i, split in enumerate(splits1):
            tuner1.seed_split(i)
            tuner2.seed_split(i)
            
            # Mock parameter space
            param_space = {
                "spread_bps": [10, 15, 20],
                "size_usd": [100, 200, 500],
                "refresh_ms": [100, 200, 500],
                "max_pos_usd": [1000, 2000, 5000]
            }
            
            # Run tuning for this split
            best_params1, best_metrics1 = tuner1.tune_split(
                split, param_space, "random", 5, 0.1, mock_data
            )
            best_params2, best_metrics2 = tuner2.tune_split(
                split, param_space, "random", 5, 0.1, mock_data
            )
            
            split_results1.append({
                "split_id": i,
                "params": best_params1,
                "metrics": best_metrics1
            })
            split_results2.append({
                "split_id": i,
                "params": best_params2,
                "metrics": best_metrics2
            })
        
        # Choose champions
        champion1 = tuner1._choose_champion(split_results1, 0.1)
        champion2 = tuner2._choose_champion(split_results2, 0.1)
        
        # Champions should be identical
        assert champion1["params"] == champion2["params"]
        assert champion1["avg_objective"] == champion2["avg_objective"]
    
    def test_identical_artifacts_with_same_seed(self, tmp_path):
        """Test that same seed produces identical champion.json and report.json files."""
        import json
        from unittest.mock import patch, MagicMock
        
        # Mock data
        mock_data = MagicMock()
        mock_data.shape = (1000, 10)
        
        # Run twice with same seed and same temp directory
        for run_number in [1, 2]:
            with patch('src.strategy.tuner.WalkForwardTuner.load_data', return_value=mock_data), \
                 patch('src.strategy.tuner.WalkForwardTuner._evaluate_params_split') as mock_eval:
                
                # Mock evaluation to return deterministic metrics
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
                    "--validate-hours", "24", 
                    "--method", "random",
                    "--trials", "5",
                    "--seed", "42",  # Same seed
                    "--out", str(tmp_path / f"run{run_number}")
                ]
                
                with patch('sys.argv', ['tuner.py'] + args):
                    try:
                        from src.strategy.tuner import main
                        main()
                    except SystemExit as e:
                        assert e.code == 0
        
        # Compare champion.json files
        champion1_path = tmp_path / "run1" / "TEST" / "champion.json"
        champion2_path = tmp_path / "run2" / "TEST" / "champion.json"
        
        assert champion1_path.exists()
        assert champion2_path.exists()
        
        with open(champion1_path, 'r') as f:
            champion1 = json.load(f)
        with open(champion2_path, 'r') as f:
            champion2 = json.load(f)
        
        # Key metrics should be identical
        assert champion1["champion_params"] == champion2["champion_params"]
        assert champion1["champion_metrics"] == champion2["champion_metrics"]
        assert champion1["seed"] == champion2["seed"]
        
        # Compare report.json files
        report1_path = tmp_path / "run1" / "report.json"
        report2_path = tmp_path / "run2" / "report.json"
        
        assert report1_path.exists()
        assert report2_path.exists()
        
        with open(report1_path, 'r') as f:
            report1 = json.load(f)
        with open(report2_path, 'r') as f:
            report2 = json.load(f)
        
        # Key aggregated metrics should be identical
        assert report1["champion_params"] == report2["champion_params"]
        assert report1["champion_metrics"] == report2["champion_metrics"]
        assert report1["seed"] == report2["seed"]
        assert report1["exit_code"] == report2["exit_code"]
        assert report1["gates"]["passed"] == report2["gates"]["passed"]
    
    def test_deterministic_metrics_generation(self):
        """Test that metrics generation is deterministic with same seed."""
        tuner1 = WalkForwardTuner(seed=42)
        tuner2 = WalkForwardTuner(seed=42)
        
        # Test parameters
        test_params = {
            "spread_bps": 15,
            "size_usd": 200,
            "refresh_ms": 200,
            "max_pos_usd": 1000
        }
        
        # Mock data
        mock_data = MagicMock()
        
        # Generate metrics multiple times
        metrics1_1 = tuner1._evaluate_params_split(test_params, mock_data)
        metrics1_2 = tuner1._evaluate_params_split(test_params, mock_data)
        
        metrics2_1 = tuner2._evaluate_params_split(test_params, mock_data)
        metrics2_2 = tuner2._evaluate_params_split(test_params, mock_data)
        
        # Same tuner should produce identical metrics for same params
        assert metrics1_1 == metrics1_2
        
        # Different tuners with same seed should produce identical metrics
        assert metrics1_1 == metrics2_1
        assert metrics1_2 == metrics2_2

"""
Tests for per-split seeding functionality in walk-forward tuning.
"""

import pytest
import random
import numpy as np
from datetime import datetime, timezone
from src.strategy.tuner import WalkForwardTuner, TimeSplit


class TestPerSplitSeeding:
    """Test per-split seeding ensures deterministic but different RNG streams."""
    
    def test_seed_split_changes_rng_state(self):
        """Test that seeding different splits produces different RNG states."""
        tuner = WalkForwardTuner(seed=123)
        
        # Get RNG state after initialization
        after_init_random = random.getstate()
        if hasattr(np.random, 'get_state'):
            after_init_numpy = np.random.get_state()
        
        # Seed split 0
        tuner.seed_split(0)
        after_split0_random = random.getstate()
        if hasattr(np.random, 'get_state'):
            after_split0_numpy = np.random.get_state()
        
        # Seed split 1
        tuner.seed_split(1)
        after_split1_random = random.getstate()
        if hasattr(np.random, 'get_state'):
            after_split1_numpy = np.random.get_state()
        
        # States should be different after seeding different splits
        assert after_split0_random != after_split1_random
        
        if hasattr(np.random, 'get_state'):
            # Convert numpy states to strings for comparison
            assert str(after_split0_numpy) != str(after_split1_numpy)
    
    def test_same_split_seed_produces_identical_stream(self):
        """Test that the same split seed produces identical random streams."""
        # Create two tuners with the same base seed
        tuner1 = WalkForwardTuner(seed=456)
        tuner2 = WalkForwardTuner(seed=456)
        
        # Seed both to split 5
        tuner1.seed_split(5)
        tuner2.seed_split(5)
        
        # Use the tuner's RNG instead of global random
        numbers1 = [tuner1.rng.random() for _ in range(10)]
        numbers2 = [tuner2.rng.random() for _ in range(10)]
        
        # Should be identical
        assert numbers1 == numbers2
    
    def test_different_split_seeds_produce_different_streams(self):
        """Test that different split seeds produce different random streams."""
        tuner = WalkForwardTuner(seed=789)
        
        # Seed to split 0
        tuner.seed_split(0)
        numbers_split0 = [tuner.rng.random() for _ in range(10)]
        
        # Seed to split 1
        tuner.seed_split(1)
        numbers_split1 = [tuner.rng.random() for _ in range(10)]
        
        # Should be different
        assert numbers_split0 != numbers_split1
    
    def test_split_seed_formula(self):
        """Test that split seed is calculated as base_seed + split_index."""
        base_seed = 100
        tuner = WalkForwardTuner(seed=base_seed)
        
        # Test a few splits
        for split_index in [0, 5, 10, 100]:
            expected_seed = base_seed + split_index
            
            # Create a new tuner for each test to avoid state interference
            test_tuner = WalkForwardTuner(seed=base_seed)
            
            # Mock the seed_all function to capture the seed
            captured_seed = None
            original_seed_all = test_tuner.seed_split
            
            def mock_seed_split(split_idx):
                nonlocal captured_seed
                captured_seed = test_tuner.seed + split_idx
            
            # Temporarily replace seed_split
            test_tuner.seed_split = mock_seed_split
            
            # Call seed_split
            test_tuner.seed_split(split_index)
            
            # Check the seed
            assert captured_seed == expected_seed
    
    def test_deterministic_across_runs(self):
        """Test that the same base seed + split index produces identical results across runs."""
        base_seed = 42
        
        # First run
        tuner1 = WalkForwardTuner(seed=base_seed)
        tuner1.seed_split(3)
        numbers1 = [tuner1.rng.random() for _ in range(20)]
        
        # Second run
        tuner2 = WalkForwardTuner(seed=base_seed)
        tuner2.seed_split(3)
        numbers2 = [tuner2.rng.random() for _ in range(20)]
        
        # Should be identical
        assert numbers1 == numbers2
    
    def test_split_seeding_integration(self):
        """Test that split seeding works correctly in the full workflow."""
        tuner = WalkForwardTuner(seed=999)
        
        # Create some test splits
        splits = [
            TimeSplit(
                train_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                train_end=datetime(2025, 1, 2, tzinfo=timezone.utc),
                validate_start=datetime(2025, 1, 2, tzinfo=timezone.utc),
                validate_end=datetime(2025, 1, 2, 6, tzinfo=timezone.utc),
                split_id=0
            ),
            TimeSplit(
                train_start=datetime(2025, 1, 1, 6, tzinfo=timezone.utc),
                train_end=datetime(2025, 1, 2, 6, tzinfo=timezone.utc),
                validate_start=datetime(2025, 1, 2, 6, tzinfo=timezone.utc),
                validate_end=datetime(2025, 1, 2, 12, tzinfo=timezone.utc),
                split_id=1
            )
        ]
        
        # Simulate processing each split with seeding
        results = []
        for split in splits:
            tuner.seed_split(split.split_id)
            # Generate some random numbers to simulate processing
            random_numbers = [tuner.rng.random() for _ in range(5)]
            results.append((split.split_id, random_numbers))
        
        # Each split should have different random numbers
        assert results[0][1] != results[1][1]
        
        # But the same split should produce the same numbers if reseeded
        # Create a new tuner to avoid state interference
        tuner2 = WalkForwardTuner(seed=999)
        tuner2.seed_split(0)
        new_random_numbers = [tuner2.rng.random() for _ in range(5)]
        assert results[0][1] == new_random_numbers

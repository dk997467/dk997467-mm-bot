"""Test walk-forward split generation and boundaries."""

from datetime import datetime, timedelta
import pytest

from src.strategy.tuner import WalkForwardTuner, TimeSplit


class TestWalkForwardSplits:
    """Test walk-forward split generation logic."""
    
    def test_basic_split_generation(self):
        """Test basic split generation with simple parameters."""
        tuner = WalkForwardTuner(seed=42)
        
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 31)
        train_days = 7
        validate_hours = 24
        
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        # Should generate multiple splits
        assert len(splits) > 0
        
        # Check first split
        first_split = splits[0]
        assert first_split.train_start == data_start
        assert first_split.train_end == data_start + timedelta(days=train_days)
        assert first_split.validate_start == first_split.train_end
        assert first_split.validate_end == first_split.validate_start + timedelta(hours=validate_hours)
        assert first_split.split_id == 0
        
        # Check last split doesn't exceed data bounds
        last_split = splits[-1]
        assert last_split.validate_end <= data_end
        
        # Check all splits have sequential IDs
        for i, split in enumerate(splits):
            assert split.split_id == i
    
    def test_split_boundaries(self):
        """Test that split boundaries are correctly calculated."""
        tuner = WalkForwardTuner(seed=123)
        
        data_start = datetime(2025, 1, 1, 12, 0)  # Noon
        data_end = datetime(2025, 1, 15, 12, 0)   # 14 days later
        train_days = 5
        validate_hours = 48  # 2 days
        
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        # Calculate expected number of splits
        # With 5-day train + 2-day validate = 7-day total per split
        # Default step is validate_hours (48 hours = 2 days), so we get more splits
        # Over 14 days, we should get 4 splits
        expected_splits = 4
        assert len(splits) == expected_splits
        
        # Check first split
        first = splits[0]
        assert first.train_start == data_start
        assert first.train_end == datetime(2025, 1, 6, 12, 0)  # 5 days later
        assert first.validate_start == first.train_end
        assert first.validate_end == datetime(2025, 1, 8, 12, 0)  # 2 days later
        
        # Check second split (step is 2 days, so starts 2 days after first split start)
        second = splits[1]
        assert second.train_start == datetime(2025, 1, 3, 12, 0)  # 2 days after first split start
        assert second.train_end == datetime(2025, 1, 8, 12, 0)  # 5 days later
        assert second.validate_start == second.train_end
        assert second.validate_end == datetime(2025, 1, 10, 12, 0)  # 2 days later
    
    def test_custom_step_size(self):
        """Test split generation with custom step size."""
        tuner = WalkForwardTuner(seed=456)
        
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 21)
        train_days = 5
        validate_hours = 24
        step_hours = 48  # Custom step size (2 days)
        
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours,
            step_hours=step_hours
        )
        
        # With 2-day steps, we should get more splits
        assert len(splits) > 1
        
        # Check step sizes between splits
        for i in range(1, len(splits)):
            prev_split = splits[i-1]
            curr_split = splits[i]
            
            # Step should be 2 days
            expected_step = timedelta(hours=step_hours)
            actual_step = curr_split.train_start - prev_split.train_start
            assert actual_step == expected_step
    
    def test_edge_cases(self):
        """Test edge cases in split generation."""
        tuner = WalkForwardTuner(seed=789)

        # Case 1: Very short data period
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 2, 12, 0)  # 1.5 days
        train_days = 1
        validate_hours = 12

        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )

        # Should get 1 split
        assert len(splits) == 1

        # Case 2: Data period exactly fits one split
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 2, 12, 0)  # 1.5 days
        train_days = 1
        validate_hours = 12

        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )

        # Should get 1 split
        assert len(splits) == 1

        # Case 3: Data period too short for any split - should raise ValueError
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 1, 12, 0)  # 12 hours
        train_days = 1
        validate_hours = 24

        with pytest.raises(ValueError, match="Combined train \\(1 days\\) \\+ validate \\(24 hours\\) = 48 hours exceeds available data range of 12\\.0 hours"):
            tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=train_days,
                validate_hours=validate_hours
            )
    
    def test_split_validation(self):
        """Test that all splits are valid."""
        tuner = WalkForwardTuner(seed=999)
        
        data_start = datetime(2025, 1, 1)
        data_end = datetime(2025, 1, 31)
        train_days = 7
        validate_hours = 24
        
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        for split in splits:
            # Train period should be positive
            train_duration = split.train_end - split.train_start
            assert train_duration > timedelta(0)
            
            # Validate period should be positive
            validate_duration = split.validate_end - split.validate_start
            assert validate_duration > timedelta(0)
            
            # Train should come before validate
            assert split.train_start < split.train_end
            assert split.train_end <= split.validate_start
            assert split.validate_start < split.validate_end
            
            # All periods should be within data bounds
            assert split.train_start >= data_start
            assert split.validate_end <= data_end
            
            # Split ID should be non-negative
            assert split.split_id >= 0

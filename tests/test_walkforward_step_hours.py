"""Test walk-forward step-hours functionality and overlapping splits."""

from datetime import datetime, timedelta, timezone
import pytest

from src.strategy.tuner import WalkForwardTuner, TimeSplit


class TestWalkForwardStepHours:
    """Test step-hours functionality in walk-forward splits."""
    
    def test_step_hours_defaults_to_validate_hours(self):
        """Test that step_hours defaults to validate_hours when not specified."""
        tuner = WalkForwardTuner(seed=42)
        
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 31, tzinfo=timezone.utc)
        train_days = 7
        validate_hours = 24
        
        # No step_hours specified
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours
        )
        
        # Should behave as if step_hours = validate_hours
        assert len(splits) > 0
        
        # Check that next split starts after previous split start + step
        for i in range(1, len(splits)):
            prev_split = splits[i-1]
            curr_split = splits[i]
            
            # Current split should start after previous split start + step
            expected_start = prev_split.train_start + timedelta(hours=validate_hours)
            assert curr_split.train_start == expected_start
    
    def test_custom_step_hours_creates_overlapping_splits(self):
        """Test that custom step_hours creates overlapping splits advancing by step size."""
        tuner = WalkForwardTuner(seed=123)
        
        data_start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)
        train_days = 2
        validate_hours = 12
        step_hours = 12  # Same as validate_hours
        
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours,
            step_hours=step_hours
        )
        
        # Should generate multiple splits
        assert len(splits) > 1
        
        # Check first split
        first = splits[0]
        assert first.train_start == data_start
        assert first.train_end == datetime(2025, 1, 3, 12, 0, tzinfo=timezone.utc)  # 2 days later
        assert first.validate_start == first.train_end
        assert first.validate_end == datetime(2025, 1, 4, 0, 0, tzinfo=timezone.utc)  # 12 hours later
        
        # Check second split (should start after first split start + step)
        second = splits[1]
        expected_start = first.train_start + timedelta(hours=step_hours)
        assert second.train_start == expected_start
        assert second.train_end == datetime(2025, 1, 4, 0, 0, tzinfo=timezone.utc)  # 2 days later
        assert second.validate_start == second.train_end
        assert second.validate_end == datetime(2025, 1, 4, 12, 0, tzinfo=timezone.utc)  # 12 hours later
        
        # Check step sizes between splits
        for i in range(1, len(splits)):
            prev_split = splits[i-1]
            curr_split = splits[i]
            
            # Step should be exactly step_hours
            expected_step = timedelta(hours=step_hours)
            actual_step = curr_split.train_start - prev_split.train_start
            assert actual_step == expected_step
    
    def test_step_hours_smaller_than_validate_hours(self):
        """Test step_hours smaller than validate_hours creates overlapping validation windows."""
        tuner = WalkForwardTuner(seed=456)
        
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 10, tzinfo=timezone.utc)
        train_days = 1
        validate_hours = 24
        step_hours = 12  # Smaller than validate_hours
        
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours,
            step_hours=step_hours
        )
        
        # Should generate multiple splits with overlapping validation windows
        assert len(splits) > 1
        
        # Check that validation windows overlap
        for i in range(1, len(splits)):
            prev_split = splits[i-1]
            curr_split = splits[i]
            
            # Current validation should start before previous validation ends
            # (due to step_hours < validate_hours)
            assert curr_split.validate_start < prev_split.validate_end
            
            # Step should be exactly step_hours
            expected_step = timedelta(hours=step_hours)
            actual_step = curr_split.train_start - prev_split.train_start
            assert actual_step == expected_step
    
    def test_step_hours_larger_than_validate_hours(self):
        """Test step_hours larger than validate_hours creates gaps between validation windows."""
        tuner = WalkForwardTuner(seed=789)
        
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 15, tzinfo=timezone.utc)
        train_days = 1
        validate_hours = 12
        step_hours = 24  # Larger than validate_hours
        
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours,
            step_hours=step_hours
        )
        
        # Should generate multiple splits with gaps between validation windows
        assert len(splits) > 1
        
        # Check that validation windows have gaps
        for i in range(1, len(splits)):
            prev_split = splits[i-1]
            curr_split = splits[i]
            
            # Current validation should start after previous validation ends
            # (due to step_hours > validate_hours)
            assert curr_split.validate_start > prev_split.validate_end
            
            # Step should be exactly step_hours
            expected_step = timedelta(hours=step_hours)
            actual_step = curr_split.train_start - prev_split.train_start
            assert actual_step == expected_step
    
    def test_step_hours_edge_cases(self):
        """Test edge cases with step_hours."""
        tuner = WalkForwardTuner(seed=999)
        
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 5, tzinfo=timezone.utc)
        
        # Case 1: step_hours = 0 (should fail or handle gracefully)
        with pytest.raises(ValueError):
            tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=1,
                validate_hours=12,
                step_hours=0
            )
        
        # Case 2: step_hours > data period
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=1,
            validate_hours=12,
            step_hours=100  # Very large step
        )
        
        # Should only get 1 split since step is too large
        assert len(splits) == 1
    
    def test_step_hours_utc_timezone_handling(self):
        """Test that step_hours works correctly with UTC timezone."""
        tuner = WalkForwardTuner(seed=111)
        
        # Use specific UTC times
        data_start = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
        train_days = 2
        validate_hours = 12
        step_hours = 6  # Small step for precise testing
        
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=train_days,
            validate_hours=validate_hours,
            step_hours=step_hours
        )
        
        # Should generate multiple splits
        assert len(splits) > 1
        
        # Check that all times are in UTC
        for split in splits:
            assert split.train_start.tzinfo == timezone.utc
            assert split.train_end.tzinfo == timezone.utc
            assert split.validate_start.tzinfo == timezone.utc
            assert split.validate_end.tzinfo == timezone.utc
        
        # Check step sizes
        for i in range(1, len(splits)):
            prev_split = splits[i-1]
            curr_split = splits[i]
            
            expected_step = timedelta(hours=step_hours)
            actual_step = curr_split.train_start - prev_split.train_start
            assert actual_step == expected_step

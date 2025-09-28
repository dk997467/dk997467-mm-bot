"""
Tests for input validation in walk-forward tuning.
"""

import pytest
import sys
from datetime import datetime, timezone
from src.strategy.tuner import WalkForwardTuner


class TestInputValidation:
    """Test input validation produces friendly error messages."""
    
    def test_step_hours_positive_validation(self):
        """Test that step_hours must be positive."""
        tuner = WalkForwardTuner(seed=123)
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 12, 31, tzinfo=timezone.utc)
        
        # Test zero step_hours
        with pytest.raises(ValueError, match="step_hours must be positive"):
            tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=30,
                validate_hours=24,
                step_hours=0
            )
        
        # Test negative step_hours
        with pytest.raises(ValueError, match="step_hours must be positive"):
            tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=30,
                validate_hours=24,
                step_hours=-5
            )
    
    def test_window_fits_data_range_validation(self):
        """Test that train + validate window fits in available data range."""
        tuner = WalkForwardTuner(seed=123)
        
        # Small data range: 2 days = 48 hours
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 3, tzinfo=timezone.utc)
        
        # Try to fit 30 days + 24 hours = 744 hours in 48 hours
        with pytest.raises(ValueError, match="Combined train \\(30 days\\) \\+ validate \\(24 hours\\) = 744 hours exceeds available data range of 48\\.0 hours"):
            tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=30,
                validate_hours=24,
                step_hours=24
            )
    
    def test_exact_window_fits_data_range(self):
        """Test that exact window size fits without error."""
        tuner = WalkForwardTuner(seed=123)
        
        # Data range: 2 days = 48 hours
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 3, tzinfo=timezone.utc)
        
        # Train: 1 day = 24 hours, Validate: 24 hours, Total: 48 hours
        # This should fit exactly
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=1,
            validate_hours=24,
            step_hours=24
        )
        
        # Should generate exactly one split
        assert len(splits) == 1
    
    def test_window_smaller_than_data_range(self):
        """Test that smaller window than data range works correctly."""
        tuner = WalkForwardTuner(seed=123)
        
        # Data range: 10 days = 240 hours
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 11, tzinfo=timezone.utc)
        
        # Train: 2 days = 48 hours, Validate: 12 hours, Total: 60 hours
        # This should fit and generate multiple splits
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=2,
            validate_hours=12,
            step_hours=24
        )
        
        # Should generate multiple splits
        assert len(splits) > 1
    
    def test_edge_case_minimal_data_range(self):
        """Test edge case with minimal data range."""
        tuner = WalkForwardTuner(seed=123)
        
        # Minimal data range: 1 hour
        data_start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 1, 1, 0, tzinfo=timezone.utc)
        
        # Try to fit 1 day + 1 hour = 25 hours in 1 hour
        with pytest.raises(ValueError, match="Combined train \\(1 days\\) \\+ validate \\(1 hours\\) = 25 hours exceeds available data range of 1\\.0 hours"):
            tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=1,
                validate_hours=1,
                step_hours=1
            )
    
    def test_edge_case_exact_fit(self):
        """Test edge case where window exactly fits data range."""
        tuner = WalkForwardTuner(seed=123)
        
        # Data range: 1 hour
        data_start = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 1, 1, 0, tzinfo=timezone.utc)
        
        # Train: 0.5 hours = 30 minutes, Validate: 0.5 hours = 30 minutes, Total: 1 hour
        # This should fit exactly
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=0,  # 0 days = 0 hours
            validate_hours=1,  # 1 hour
            step_hours=1
        )
        
        # Should generate exactly one split
        assert len(splits) == 1
    
    def test_error_message_clarity(self):
        """Test that error messages are clear and helpful."""
        tuner = WalkForwardTuner(seed=123)
        
        # Data range: 1 day = 24 hours
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 2, tzinfo=timezone.utc)
        
        # Try to fit 2 days + 1 hour = 49 hours in 24 hours
        with pytest.raises(ValueError) as exc_info:
            tuner.generate_splits(
                data_start=data_start,
                data_end=data_end,
                train_days=2,
                validate_hours=1,
                step_hours=1
            )
        
        error_msg = str(exc_info.value)
        
        # Error message should be clear and include:
        # - Train days
        # - Validate hours
        # - Total window size
        # - Available data range
        assert "train (2 days)" in error_msg
        assert "validate (1 hours)" in error_msg
        assert "49 hours" in error_msg
        assert "24.0 hours" in error_msg
        assert "exceeds available data range" in error_msg
    
    def test_step_hours_default_behavior(self):
        """Test that step_hours defaults to validate_hours when not specified."""
        tuner = WalkForwardTuner(seed=123)
        
        # Data range: 5 days = 120 hours
        data_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        data_end = datetime(2025, 1, 6, tzinfo=timezone.utc)
        
        # Don't specify step_hours, should default to validate_hours (24)
        splits = tuner.generate_splits(
            data_start=data_start,
            data_end=data_end,
            train_days=1,
            validate_hours=24
            # step_hours not specified
        )
        
        # Should generate multiple splits with 24-hour step
        assert len(splits) > 1
        
        # Check that splits are spaced by 24 hours
        for i in range(1, len(splits)):
            time_diff = splits[i].train_start - splits[i-1].train_start
            expected_hours = 24
            assert time_diff.total_seconds() == expected_hours * 3600

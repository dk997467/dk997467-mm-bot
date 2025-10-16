"""
Tests for oscillation detector, velocity bounds, and cooldown guard.

Covers three core scenarios:
1. Oscillation detection (A→B→A pattern suppression)
2. Velocity bounds (rate limiting)
3. Cooldown after large deltas
"""
import sys
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.soak.iter_watcher import oscillates, within_velocity, apply_cooldown_if_needed


class TestOscillationDetector:
    """Test oscillation pattern detection."""
    
    def test_simple_aba_pattern_detected(self):
        """Test A→B→A oscillation is detected."""
        seq = [1.0, 2.0, 1.0]
        assert oscillates(seq, window=3) is True
    
    def test_no_oscillation_monotonic(self):
        """Test monotonic sequence has no oscillation."""
        seq = [1.0, 2.0, 3.0]
        assert oscillates(seq, window=3) is False
    
    def test_no_oscillation_random(self):
        """Test random walk has no oscillation."""
        seq = [1.0, 2.5, 1.8, 3.2]
        assert oscillates(seq, window=3) is False
    
    def test_tolerance_respected(self):
        """Test tolerance parameter for float comparison."""
        # Within tolerance: should detect oscillation
        seq = [1.0, 2.0, 1.00001]
        assert oscillates(seq, tol=0.001, window=3) is True
        
        # Outside tolerance: no oscillation
        seq = [1.0, 2.0, 1.1]
        assert oscillates(seq, tol=0.001, window=3) is False
    
    def test_insufficient_data(self):
        """Test insufficient data returns False."""
        assert oscillates([1.0], window=3) is False
        assert oscillates([1.0, 2.0], window=3) is False
    
    def test_window_4_alternating(self):
        """Test A→B→A→B pattern (window=4)."""
        seq = [1.0, 2.0, 1.0, 2.0]
        assert oscillates(seq, window=4) is True
        
        # Not alternating
        seq = [1.0, 2.0, 1.0, 3.0]
        assert oscillates(seq, window=4) is False
    
    def test_real_world_spread_oscillation(self):
        """Test realistic spread parameter oscillation."""
        # Spread oscillates between 0.14 and 0.16
        spreads = [0.14, 0.16, 0.14]
        assert oscillates(spreads, tol=1e-6, window=3) is True
        
        # Spread trending up (no oscillation)
        spreads = [0.14, 0.15, 0.16]
        assert oscillates(spreads, tol=1e-6, window=3) is False


class TestVelocityBounds:
    """Test velocity/rate limiting for parameter changes."""
    
    def test_change_within_velocity(self):
        """Test change within allowed velocity passes."""
        # Change of 5 in 1 hour, max=10/h → OK
        assert within_velocity(100, 105, max_change_per_hour=10, elapsed_hours=1.0) is True
    
    def test_change_exceeds_velocity(self):
        """Test change exceeding velocity is rejected."""
        # Change of 20 in 1 hour, max=10/h → Reject
        assert within_velocity(100, 120, max_change_per_hour=10, elapsed_hours=1.0) is False
    
    def test_large_change_allowed_over_time(self):
        """Test large change is allowed if enough time elapsed."""
        # Change of 50 in 5 hours, max=10/h → OK (50 ≤ 50)
        assert within_velocity(100, 150, max_change_per_hour=10, elapsed_hours=5.0) is True
    
    def test_zero_elapsed_time_rejected(self):
        """Test instantaneous change is always rejected."""
        assert within_velocity(100, 105, max_change_per_hour=10, elapsed_hours=0.0) is False
    
    def test_negative_elapsed_time_rejected(self):
        """Test negative elapsed time is rejected."""
        assert within_velocity(100, 105, max_change_per_hour=10, elapsed_hours=-1.0) is False
    
    def test_decrease_velocity_also_checked(self):
        """Test velocity check works for decreases."""
        # Decrease of 20 in 1 hour, max=10/h → Reject
        assert within_velocity(100, 80, max_change_per_hour=10, elapsed_hours=1.0) is False
        
        # Decrease of 5 in 1 hour, max=10/h → OK
        assert within_velocity(100, 95, max_change_per_hour=10, elapsed_hours=1.0) is True
    
    def test_real_world_spread_velocity(self):
        """Test realistic spread parameter velocity."""
        # Spread change from 0.14 to 0.20 in 0.5h (6 BPS change in 30 min)
        # Max velocity: 10 BPS/hour → 5 BPS allowed in 0.5h
        # 6 BPS > 5 BPS → Reject
        assert within_velocity(
            0.14, 0.20,
            max_change_per_hour=0.10,  # 10 BPS/hour
            elapsed_hours=0.5
        ) is False
        
        # Same change over 1 hour → OK
        assert within_velocity(
            0.14, 0.20,
            max_change_per_hour=0.10,
            elapsed_hours=1.0
        ) is True


class TestCooldownGuard:
    """Test cooldown mechanism after large deltas."""
    
    def test_large_delta_triggers_cooldown(self):
        """Test large delta triggers cooldown."""
        result = apply_cooldown_if_needed(
            delta_magnitude=0.15,
            threshold=0.10,
            cooldown_iters=3,
            current_cooldown_remaining=0
        )
        
        assert result["should_apply"] is True  # First delta is applied
        assert result["cooldown_active"] is True
        assert result["cooldown_remaining"] == 3
        assert result["reason"] == "large_delta_triggers_cooldown"
    
    def test_cooldown_active_blocks_changes(self):
        """Test active cooldown blocks subsequent changes."""
        result = apply_cooldown_if_needed(
            delta_magnitude=0.05,  # Small delta
            threshold=0.10,
            cooldown_iters=3,
            current_cooldown_remaining=2  # Cooldown active
        )
        
        assert result["should_apply"] is False  # Blocked by cooldown
        assert result["cooldown_active"] is True
        assert result["cooldown_remaining"] == 1  # Decremented
        assert result["reason"] == "cooldown_active"
    
    def test_cooldown_expires_after_iterations(self):
        """Test cooldown expires and allows changes."""
        # Iteration 1: cooldown_remaining=2
        result1 = apply_cooldown_if_needed(0.05, 0.10, 3, current_cooldown_remaining=2)
        assert result1["should_apply"] is False
        assert result1["cooldown_remaining"] == 1
        
        # Iteration 2: cooldown_remaining=1
        result2 = apply_cooldown_if_needed(0.05, 0.10, 3, current_cooldown_remaining=1)
        assert result2["should_apply"] is False
        assert result2["cooldown_remaining"] == 0
        
        # Iteration 3: cooldown_remaining=0 → Normal operation
        result3 = apply_cooldown_if_needed(0.05, 0.10, 3, current_cooldown_remaining=0)
        assert result3["should_apply"] is True
        assert result3["cooldown_active"] is False
        assert result3["reason"] == "normal"
    
    def test_small_delta_no_cooldown(self):
        """Test small delta does not trigger cooldown."""
        result = apply_cooldown_if_needed(
            delta_magnitude=0.05,
            threshold=0.10,
            cooldown_iters=3,
            current_cooldown_remaining=0
        )
        
        assert result["should_apply"] is True
        assert result["cooldown_active"] is False
        assert result["cooldown_remaining"] == 0
        assert result["reason"] == "normal"
    
    def test_real_world_spread_cooldown(self):
        """Test realistic spread parameter cooldown."""
        # Large spread widening (0.14 → 0.25 = 0.11 delta)
        # Threshold: 0.10 → triggers 3-iteration cooldown
        result = apply_cooldown_if_needed(
            delta_magnitude=0.11,
            threshold=0.10,
            cooldown_iters=3,
            current_cooldown_remaining=0
        )
        
        assert result["should_apply"] is True
        assert result["cooldown_active"] is True
        assert result["cooldown_remaining"] == 3


class TestIntegrationScenarios:
    """Integration tests combining oscillation, velocity, and cooldown."""
    
    def test_oscillation_suppression_workflow(self):
        """
        Scenario 1: A→B→A pattern should be suppressed.
        
        Flow:
        1. Param at 100
        2. Delta +20 (oscillates to 120)
        3. Delta -20 (oscillates back to 100)
        4. Oscillation detected → suppress delta
        """
        history = [100, 120, 100]
        
        # Detect oscillation
        assert oscillates(history, window=3) is True
        
        # In real code, this would suppress the next delta
        # Here we just validate detection works
    
    def test_velocity_rejection_workflow(self):
        """
        Scenario 2: Rapid changes should be rejected.
        
        Flow:
        1. Param at 100
        2. Proposed change to 130 in 1 hour
        3. Max velocity: 20/hour
        4. Delta rejected (30 > 20)
        """
        old_val = 100
        new_val = 130
        
        is_allowed = within_velocity(
            old_val, new_val,
            max_change_per_hour=20,
            elapsed_hours=1.0
        )
        
        assert is_allowed is False
    
    def test_cooldown_workflow(self):
        """
        Scenario 3: Large delta triggers cooldown.
        
        Flow:
        1. Large delta (0.15) applied
        2. Cooldown triggered (3 iterations)
        3. Next 3 iterations: all deltas blocked
        4. Iteration 4: back to normal
        """
        # Iteration 1: Large delta
        result1 = apply_cooldown_if_needed(0.15, 0.10, 3, 0)
        assert result1["should_apply"] is True
        assert result1["cooldown_remaining"] == 3
        
        # Iterations 2-4: Cooldown active
        for i in range(3):
            remaining = 3 - i - 1
            result = apply_cooldown_if_needed(0.05, 0.10, 3, 3 - i)
            assert result["should_apply"] is False
            assert result["cooldown_remaining"] == remaining
        
        # Iteration 5: Cooldown expired
        result5 = apply_cooldown_if_needed(0.05, 0.10, 3, 0)
        assert result5["should_apply"] is True
        assert result5["cooldown_active"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


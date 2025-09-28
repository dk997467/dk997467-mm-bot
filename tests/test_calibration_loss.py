"""
Tests for E2 Part 1 calibration loss functions.
"""

import pytest
import numpy as np

from src.research.calibrate import (
    ks_distance_cdf, ks_distance_bins, rates_from_bins, loss_components,
    round_floats, ks_distance_cdf_quantiles, ks_distance_bins_norm,
    ensure_monotonic_cdf, resample_quantiles, get_percentiles_bins,
    DEFAULT_PERCENTILES, DEFAULT_BINS_MAX_BPS
)


class TestCalibrationLoss:
    """Test loss calculation functions."""

    def test_ks_distance_cdf_identical_distributions(self):
        """Test KS distance is 0 for identical CDFs."""
        cdf_a = [
            {"p": 0.25, "v": 100.0},
            {"p": 0.5, "v": 150.0},
            {"p": 0.75, "v": 200.0},
            {"p": 0.9, "v": 250.0}
        ]
        cdf_b = cdf_a.copy()
        
        distance = ks_distance_cdf(cdf_a, cdf_b)
        assert distance == 0.0, "Identical CDFs should have KS distance 0"

    def test_ks_distance_cdf_different_distributions(self):
        """Test KS distance for different CDFs."""
        cdf_a = [
            {"p": 0.25, "v": 100.0},
            {"p": 0.5, "v": 150.0},
            {"p": 0.75, "v": 200.0},
            {"p": 0.9, "v": 250.0}
        ]
        
        # Shifted distribution
        cdf_b = [
            {"p": 0.25, "v": 200.0},  # +100ms shift
            {"p": 0.5, "v": 250.0},
            {"p": 0.75, "v": 300.0},
            {"p": 0.9, "v": 350.0}
        ]
        
        distance = ks_distance_cdf(cdf_a, cdf_b)
        assert 0.0 < distance <= 1.0, "Different CDFs should have positive KS distance"

    def test_ks_distance_cdf_empty_distributions(self):
        """Test KS distance with empty distributions."""
        cdf_empty = []
        cdf_normal = [{"p": 0.5, "v": 100.0}]
        
        # Empty vs empty should be 0 (edge case)
        distance = ks_distance_cdf(cdf_empty, cdf_empty)
        assert distance == 1.0, "Empty vs empty should return max distance"
        
        # Empty vs normal should be max distance
        distance = ks_distance_cdf(cdf_empty, cdf_normal)
        assert distance == 1.0, "Empty vs normal should return max distance"
        
        distance = ks_distance_cdf(cdf_normal, cdf_empty)
        assert distance == 1.0, "Normal vs empty should return max distance"

    def test_ks_distance_cdf_monotonicity(self):
        """Test that KS distance increases with distribution separation."""
        base_cdf = [
            {"p": 0.5, "v": 100.0},
            {"p": 0.9, "v": 200.0}
        ]
        
        # Create increasingly separated distributions
        small_shift = [
            {"p": 0.5, "v": 110.0},  # +10ms
            {"p": 0.9, "v": 210.0}
        ]
        
        large_shift = [
            {"p": 0.5, "v": 150.0},  # +50ms
            {"p": 0.9, "v": 250.0}
        ]
        
        distance_small = ks_distance_cdf(base_cdf, small_shift)
        distance_large = ks_distance_cdf(base_cdf, large_shift)
        
        assert distance_small < distance_large, "Larger shifts should have larger KS distance"

    def test_rates_from_bins(self):
        """Test conversion from bin data to hit rates."""
        hit_rate_by_bin = {
            "0": {"count": 100, "fills": 20},  # 20% hit rate
            "5": {"count": 80, "fills": 8},    # 10% hit rate
            "10": {"count": 60, "fills": 0},   # 0% hit rate
            "invalid": {"count": 10, "fills": 5}  # Should be ignored
        }
        
        rates = rates_from_bins(hit_rate_by_bin)
        
        assert rates[0] == 0.2, "Bin 0 should have 20% hit rate"
        assert rates[5] == 0.1, "Bin 5 should have 10% hit rate"
        assert rates[10] == 0.0, "Bin 10 should have 0% hit rate"
        assert "invalid" not in rates, "Invalid bin keys should be ignored"

    def test_rates_from_bins_zero_count(self):
        """Test rates calculation with zero counts."""
        hit_rate_by_bin = {
            "0": {"count": 0, "fills": 0},     # 0 count -> 0 rate
            "5": {"count": 100, "fills": 50},  # Normal case
        }
        
        rates = rates_from_bins(hit_rate_by_bin)
        
        assert rates[0] == 0.0, "Zero count should give 0% hit rate"
        assert rates[5] == 0.5, "Normal case should work"

    def test_ks_distance_bins_identical_rates(self):
        """Test KS distance is 0 for identical bin rates."""
        rates_a = {0: 0.2, 5: 0.1, 10: 0.05}
        rates_b = rates_a.copy()
        
        distance = ks_distance_bins(rates_a, rates_b, bins_max_bps=10)
        assert distance == 0.0, "Identical rates should have KS distance 0"

    def test_ks_distance_bins_different_rates(self):
        """Test KS distance for different bin rates."""
        rates_a = {0: 0.2, 5: 0.1, 10: 0.05}
        rates_b = {0: 0.1, 5: 0.2, 10: 0.05}  # Swapped rates for bins 0 and 5
        
        distance = ks_distance_bins(rates_a, rates_b, bins_max_bps=10)
        assert 0.0 < distance <= 1.0, "Different rates should have positive KS distance"

    def test_ks_distance_bins_missing_bins(self):
        """Test KS distance handles missing bins correctly."""
        rates_a = {0: 0.2, 10: 0.1}  # Missing bin 5
        rates_b = {0: 0.2, 5: 0.1, 10: 0.1}  # Has all bins
        
        distance = ks_distance_bins(rates_a, rates_b, bins_max_bps=10)
        assert 0.0 < distance <= 1.0, "Missing bins should affect KS distance"

    def test_ks_distance_bins_empty_rates(self):
        """Test KS distance with empty rate distributions."""
        rates_empty = {}
        rates_normal = {0: 0.1, 5: 0.2}
        
        # Empty vs empty
        distance = ks_distance_bins(rates_empty, rates_empty, bins_max_bps=10)
        assert distance == 0.0, "Empty vs empty rates should be 0"
        
        # Empty vs normal  
        distance = ks_distance_bins(rates_empty, rates_normal, bins_max_bps=10)
        assert distance == 1.0, "Empty vs normal rates should be max distance"

    def test_loss_components_basic(self):
        """Test basic loss components calculation."""
        live = {
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 100.0}],
            "hit_rate_by_bin": {"0": {"count": 100, "fills": 20}},
            "live_hit": 0.2,
            "live_maker": 0.15
        }
        
        sim = {
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 120.0}],  # 20ms difference
            "hit_rate_by_bin": {"0": {"count": 100, "fills": 25}},  # Different hit rate
            "sim_hit": 0.25,  # 5% difference
            "sim_maker": 0.20  # 5% difference
        }
        
        loss = loss_components(live, sim)
        
        # Check all components are present
        assert "KS_queue" in loss
        assert "KS_bins" in loss
        assert "L_hit" in loss
        assert "L_maker" in loss
        assert "L_reg" in loss
        assert "TotalLoss" in loss
        
        # Check values are reasonable
        assert 0.0 <= loss["KS_queue"] <= 1.0
        assert 0.0 <= loss["KS_bins"] <= 1.0
        assert loss["L_hit"] == 0.05  # |0.25 - 0.20|
        assert loss["L_maker"] == 0.05  # |0.20 - 0.15|
        assert loss["L_reg"] == 0.0  # No regularization
        
        # Total should be sum of weighted components
        expected_total = (loss["KS_queue"] + loss["KS_bins"] + 
                         loss["L_hit"] + loss["L_maker"] + loss["L_reg"])
        assert abs(loss["TotalLoss"] - expected_total) < 1e-10

    def test_loss_components_with_weights(self):
        """Test loss components with custom weights."""
        live = {
            "queue_wait_cdf_ms": [],
            "hit_rate_by_bin": {},
            "live_hit": 0.2,
            "live_maker": 0.15
        }
        
        sim = {
            "queue_wait_cdf_ms": [],
            "hit_rate_by_bin": {},
            "sim_hit": 0.25,
            "sim_maker": 0.20
        }
        
        weights = {
            "KS_queue": 0.5,
            "KS_bins": 0.5,
            "L_hit": 2.0,   # Double weight
            "L_maker": 3.0, # Triple weight
            "L_reg": 0.0
        }
        
        loss = loss_components(live, sim, weights=weights)
        
        # Check weighted calculation
        assert loss["L_hit"] == 0.05  # Raw difference
        assert loss["L_maker"] == 0.05  # Raw difference
        
        # Total should reflect weights
        expected_total = (0.5 * loss["KS_queue"] + 0.5 * loss["KS_bins"] +
                         2.0 * loss["L_hit"] + 3.0 * loss["L_maker"])
        assert abs(loss["TotalLoss"] - expected_total) < 1e-10

    def test_loss_components_with_regularization(self):
        """Test loss components with L2 regularization."""
        live = {
            "queue_wait_cdf_ms": [],
            "hit_rate_by_bin": {},
            "live_hit": 0.2,
            "live_maker": 0.15
        }
        
        sim = {
            "queue_wait_cdf_ms": [],
            "hit_rate_by_bin": {},
            "sim_hit": 0.2,
            "sim_maker": 0.15
        }
        
        baseline_params = {"param1": 1.0, "param2": 2.0}
        current_params = {"param1": 1.5, "param2": 2.2}  # 0.5^2 + 0.2^2 = 0.29
        
        loss = loss_components(
            live, sim,
            reg_l2=0.1,
            baseline_params=baseline_params,
            params=current_params
        )
        
        expected_l_reg = 0.1 * (0.5*0.5 + 0.2*0.2)  # 0.1 * 0.29 = 0.029
        assert abs(loss["L_reg"] - expected_l_reg) < 1e-10

    def test_loss_components_missing_maker_data(self):
        """Test loss components when maker data is missing."""
        live = {
            "queue_wait_cdf_ms": [],
            "hit_rate_by_bin": {},
            "live_hit": 0.2,
            "live_maker": None  # Missing
        }
        
        sim = {
            "queue_wait_cdf_ms": [],
            "hit_rate_by_bin": {},
            "sim_hit": 0.25,
            "sim_maker": 0.20
        }
        
        loss = loss_components(live, sim)
        
        assert loss["L_maker"] == 0.0, "Missing maker data should result in 0 loss"

    def test_round_floats_recursive(self):
        """Test recursive float rounding."""
        data = {
            "float_val": 3.14159265359,
            "int_val": 42,
            "str_val": "test",
            "list_val": [1.234567, 2.345678],
            "nested": {
                "deep_float": 9.87654321,
                "deep_list": [1.111111, 2.222222]
            }
        }
        
        rounded = round_floats(data, dp=3)
        
        assert rounded["float_val"] == 3.142
        assert rounded["int_val"] == 42  # Unchanged
        assert rounded["str_val"] == "test"  # Unchanged
        assert rounded["list_val"] == [1.235, 2.346]
        assert rounded["nested"]["deep_float"] == 9.877
        assert rounded["nested"]["deep_list"] == [1.111, 2.222]

    def test_round_floats_edge_cases(self):
        """Test float rounding edge cases."""
        # Test with different types
        assert round_floats(None, 2) is None
        assert round_floats(42, 2) == 42
        assert round_floats("string", 2) == "string"
        assert round_floats(3.14159, 2) == 3.14
        
        # Test with tuple (should preserve type)
        result = round_floats((1.234, 2.567), 1)
        assert isinstance(result, tuple)
        assert result == (1.2, 2.6)
        
        # Test with very small numbers
        small_num = 1e-10
        rounded_small = round_floats(small_num, 3)
        assert rounded_small == 0.0

    # E2 Part 1 Polish: New tests for normalized KS and CDF guards

    def test_ks_cdf_normalized_range(self):
        """Test that KS CDF distance is normalized to [0,1]."""
        # Create CDFs with known differences
        live_cdf = [
            {"p": 0.1, "v": 100.0},
            {"p": 0.5, "v": 200.0},
            {"p": 0.9, "v": 300.0}
        ]
        
        # SIM with constant offset (should give predictable KS)
        sim_cdf = [
            {"p": 0.1, "v": 150.0},  # +50ms
            {"p": 0.5, "v": 250.0},  # +50ms
            {"p": 0.9, "v": 350.0}   # +50ms
        ]
        
        ks_distance = ks_distance_cdf_quantiles(live_cdf, sim_cdf)
        
        # Should be in [0,1]
        assert 0.0 <= ks_distance <= 1.0, f"KS distance {ks_distance} not in [0,1]"
        
        # With IQR scaling: live IQR = 300-100 = 200, max_diff = 50
        # Expected: 50/200 = 0.25
        assert abs(ks_distance - 0.25) < 0.01, f"Expected ~0.25, got {ks_distance}"

    def test_ks_cdf_normalized_extreme_cases(self):
        """Test KS CDF normalization with extreme cases."""
        base_cdf = [{"p": 0.5, "v": 100.0}]
        
        # Test with identical CDFs
        ks_identical = ks_distance_cdf_quantiles(base_cdf, base_cdf)
        assert ks_identical == 0.0, "Identical CDFs should have 0 distance"
        
        # Test with empty CDFs
        ks_empty = ks_distance_cdf_quantiles([], base_cdf)
        assert ks_empty == 1.0, "Empty vs non-empty should be max distance"
        
        # Test with very different CDFs
        extreme_cdf = [{"p": 0.5, "v": 1000000.0}]  # Very large value
        ks_extreme = ks_distance_cdf_quantiles(base_cdf, extreme_cdf)
        assert 0.0 <= ks_extreme <= 1.0, "Extreme differences should still be in [0,1]"

    def test_ks_bins_normalized_range(self):
        """Test that KS bins distance is normalized to [0,1]."""
        live_rates = {0: 0.3, 5: 0.2, 10: 0.1}
        sim_rates = {0: 0.8, 5: 0.7, 10: 0.6}  # All rates +0.5
        
        ks_distance = ks_distance_bins_norm(live_rates, sim_rates)
        
        # Should be in [0,1]
        assert 0.0 <= ks_distance <= 1.0, f"KS bins distance {ks_distance} not in [0,1]"
        
        # Max difference is 0.5, should be the KS distance
        assert abs(ks_distance - 0.5) < 0.01, f"Expected ~0.5, got {ks_distance}"

    def test_ks_bins_normalized_edge_cases(self):
        """Test KS bins normalization edge cases."""
        rates_a = {0: 0.2, 5: 0.3}
        
        # Identical rates
        ks_identical = ks_distance_bins_norm(rates_a, rates_a)
        assert ks_identical == 0.0, "Identical rates should have 0 distance"
        
        # Empty vs non-empty
        ks_empty = ks_distance_bins_norm({}, rates_a)
        assert ks_empty == 1.0, "Empty vs non-empty should be max distance"
        
        # Both empty
        ks_both_empty = ks_distance_bins_norm({}, {})
        assert ks_both_empty == 0.0, "Both empty should be 0 distance"

    def test_ensure_monotonic_cdf_basic(self):
        """Test CDF monotonicity enforcement."""
        # Non-monotonic input
        cdf_input = [
            {"p": 0.5, "v": 200.0},
            {"p": 0.1, "v": 100.0},  # Out of order
            {"p": 0.9, "v": 180.0}   # Non-increasing v
        ]
        
        cleaned_cdf = ensure_monotonic_cdf(cdf_input)
        
        # Should be sorted by p
        assert len(cleaned_cdf) == 3
        assert cleaned_cdf[0]["p"] == 0.1
        assert cleaned_cdf[1]["p"] == 0.5
        assert cleaned_cdf[2]["p"] == 0.9
        
        # Values should be non-decreasing
        for i in range(1, len(cleaned_cdf)):
            assert cleaned_cdf[i]["v"] >= cleaned_cdf[i-1]["v"], f"Values not non-decreasing at {i}"

    def test_ensure_monotonic_cdf_deduplication(self):
        """Test CDF deduplication by percentile."""
        cdf_input = [
            {"p": 0.5, "v": 100.0},
            {"p": 0.5, "v": 200.0},  # Duplicate p, should keep last
            {"p": 0.9, "v": 300.0}
        ]
        
        cleaned_cdf = ensure_monotonic_cdf(cdf_input)
        
        assert len(cleaned_cdf) == 2
        assert cleaned_cdf[0]["p"] == 0.5
        assert cleaned_cdf[0]["v"] == 200.0  # Should keep the last value
        assert cleaned_cdf[1]["p"] == 0.9

    def test_ensure_monotonic_cdf_invalid_input(self):
        """Test CDF guard with invalid input."""
        # Empty input
        assert ensure_monotonic_cdf([]) == []
        
        # All invalid entries
        with pytest.raises(ValueError, match="CDF contains no valid entries"):
            ensure_monotonic_cdf([{"p": "invalid", "v": "invalid"}])

    def test_resample_quantiles_interpolation(self):
        """Test CDF resampling with interpolation."""
        cdf_input = [
            {"p": 0.0, "v": 0.0},
            {"p": 0.5, "v": 100.0},
            {"p": 1.0, "v": 200.0}
        ]
        
        target_percentiles = [0.25, 0.75]
        resampled = resample_quantiles(cdf_input, target_percentiles)
        
        assert len(resampled) == 2
        assert resampled[0]["p"] == 0.25
        assert resampled[0]["v"] == 50.0  # Linear interpolation: 0 + 0.25*200 = 50
        assert resampled[1]["p"] == 0.75
        assert resampled[1]["v"] == 150.0  # Linear interpolation: 100 + 0.5*100 = 150

    def test_resample_quantiles_edge_cases(self):
        """Test CDF resampling edge cases."""
        # Empty inputs
        assert resample_quantiles([], [0.5]) == []
        assert resample_quantiles([{"p": 0.5, "v": 100}], []) == []
        
        # Percentiles outside CDF range
        cdf_input = [{"p": 0.3, "v": 100.0}, {"p": 0.7, "v": 200.0}]
        resampled = resample_quantiles(cdf_input, [0.1, 0.5, 0.9])
        
        assert len(resampled) == 3
        assert resampled[0]["v"] == 100.0  # Clamped to min
        assert resampled[2]["v"] == 200.0  # Clamped to max

    def test_get_percentiles_bins_priority(self):
        """Test centralized config priority: CLI > metadata > defaults."""
        # Test CLI priority
        cli_percentiles = [0.25, 0.5, 0.75]
        cli_bins = 30
        live_meta = [{"percentiles_used": [0.1, 0.9], "bins_max_bps": 20}]
        
        percentiles, bins_max = get_percentiles_bins(cli_percentiles, cli_bins, live_meta)
        
        assert percentiles == [0.25, 0.5, 0.75]  # CLI wins
        assert bins_max == 30  # CLI wins
        
        # Test metadata priority (no CLI)
        percentiles, bins_max = get_percentiles_bins(None, None, live_meta)
        
        assert percentiles == [0.1, 0.9]  # From metadata
        assert bins_max == 20  # From metadata
        
        # Test defaults priority (no CLI, no metadata)
        percentiles, bins_max = get_percentiles_bins(None, None, [])
        
        assert percentiles == list(DEFAULT_PERCENTILES)  # Defaults
        assert bins_max == DEFAULT_BINS_MAX_BPS  # Defaults

    def test_get_percentiles_bins_deduplication(self):
        """Test that percentiles are deduplicated and sorted."""
        cli_percentiles = [0.9, 0.5, 0.9, 0.1]  # Duplicates and unsorted
        
        percentiles, _ = get_percentiles_bins(cli_percentiles, 50, [])
        
        assert percentiles == [0.1, 0.5, 0.9]  # Sorted and deduplicated


class TestKSClamp:
    """Test KS value clamping to [0,1] range."""
    
    def test_clamp01_basic_functionality(self):
        """Test clamp01 function handles various input ranges."""
        from src.research.calibrate import clamp01
        
        # Test normal range [0,1]
        assert clamp01(0.0) == 0.0
        assert clamp01(0.5) == 0.5
        assert clamp01(1.0) == 1.0
        
        # Test values below 0
        assert clamp01(-0.1) == 0.0
        assert clamp01(-10.0) == 0.0
        assert clamp01(-1e6) == 0.0
        
        # Test values above 1
        assert clamp01(1.1) == 1.0
        assert clamp01(5.0) == 1.0
        assert clamp01(1e6) == 1.0
        
        # Test edge cases
        assert clamp01(0.0001) == 0.0001
        assert clamp01(0.9999) == 0.9999
    
    def test_clamp01_with_extreme_values(self):
        """Test clamp01 with extreme floating point values."""
        from src.research.calibrate import clamp01
        import math
        
        # Test infinity
        assert clamp01(float('inf')) == 1.0
        assert clamp01(float('-inf')) == 0.0
        
        # Test very small/large values
        assert clamp01(1e-15) == 1e-15  # Should preserve small positive values
        assert clamp01(-1e-15) == 0.0   # Should clamp small negative values
        assert clamp01(1e15) == 1.0     # Should clamp large values
        
        # Test NaN (should preserve NaN behavior or handle gracefully)
        nan_result = clamp01(float('nan'))
        assert math.isnan(nan_result) or nan_result == 0.0 or nan_result == 1.0
    
    def test_ks_normalization_in_loss_calculation(self):
        """Test that KS distances are properly normalized to [0,1] in practice."""
        from src.research.calibrate import ks_distance_cdf_quantiles, ks_distance_bins_norm
        
        # Create extreme CDFs that would normally produce KS > 1
        live_cdf = [
            {"p": 0.25, "v": 100.0},
            {"p": 0.5, "v": 200.0},
            {"p": 0.75, "v": 300.0},
            {"p": 0.9, "v": 400.0}
        ]
        
        # Very different SIM CDF
        sim_cdf = [
            {"p": 0.25, "v": 1000.0},  # Very different values
            {"p": 0.5, "v": 2000.0},
            {"p": 0.75, "v": 3000.0},
            {"p": 0.9, "v": 4000.0}
        ]
        
        ks_distance = ks_distance_cdf_quantiles(live_cdf, sim_cdf)
        
        # Should be normalized to [0,1]
        assert 0.0 <= ks_distance <= 1.0, f"KS distance should be in [0,1], got {ks_distance}"
        
        # Test bins normalization
        live_rates = {0: 0.1, 5: 0.3, 10: 0.6}
        sim_rates = {0: 0.9, 5: 0.1, 10: 0.05}  # Very different rates
        
        ks_bins = ks_distance_bins_norm(live_rates, sim_rates)
        
        # Should be normalized to [0,1]
        assert 0.0 <= ks_bins <= 1.0, f"KS bins distance should be in [0,1], got {ks_bins}"

"""
Tests for backtest integration with calibration parameters.
"""

import pytest
import json
import tempfile
from unittest.mock import patch, MagicMock

from src.backtest.run import compute_sim_distributions


class TestBacktestWithCalibration:
    """Test backtest integration with E2 calibration parameters."""

    def test_compute_sim_distributions_structure(self):
        """Test that compute_sim_distributions returns correct structure."""
        # Mock backtest metrics
        mock_metrics = {
            "trading_metrics": {
                "total_quotes": 1000,
                "total_fills": 250,
                "avg_queue_wait_ms": 180.5,
                "hit_rate": 0.25,
                "maker_share": 0.80,
                "net_pnl_usd": 125.50
            },
            "queue_metrics": {
                "wait_times_ms": [100, 150, 200, 250, 300] * 50,
                "percentiles": {
                    "50": 180.0,
                    "90": 280.0,
                    "95": 320.0,
                    "99": 380.0
                }
            },
            "order_metrics": {
                "fills_by_distance": {
                    "0_bps": 80,
                    "5_bps": 70,
                    "10_bps": 60,
                    "15_bps": 40
                },
                "total_orders_by_distance": {
                    "0_bps": 300,
                    "5_bps": 300,
                    "10_bps": 250,
                    "15_bps": 150
                }
            }
        }
        
        bins_max_bps = 20
        percentiles = [0.25, 0.5, 0.75, 0.9, 0.95]
        
        sim_distributions = compute_sim_distributions(mock_metrics, bins_max_bps, percentiles)
        
        # Validate structure
        assert isinstance(sim_distributions, dict)
        
        required_keys = {"queue_wait_cdf_ms", "hit_rate_by_bin", "sim_hit", "sim_maker"}
        assert all(key in sim_distributions for key in required_keys), f"Missing required keys"
        
        # Validate queue_wait_cdf_ms
        cdf = sim_distributions["queue_wait_cdf_ms"]
        assert isinstance(cdf, list)
        assert len(cdf) == len(percentiles)
        
        for entry in cdf:
            assert "p" in entry and "v" in entry
            assert 0.0 <= entry["p"] <= 1.0
            assert entry["v"] >= 0.0
        
        # Validate hit_rate_by_bin
        bins = sim_distributions["hit_rate_by_bin"]
        assert isinstance(bins, dict)
        
        for bin_key, bin_data in bins.items():
            assert isinstance(bin_key, str)
            assert int(bin_key) <= bins_max_bps
            assert "count" in bin_data and "fills" in bin_data
            assert bin_data["count"] >= bin_data["fills"] >= 0
        
        # Validate overall metrics
        assert 0.0 <= sim_distributions["sim_hit"] <= 1.0
        assert sim_distributions["sim_maker"] is None or 0.0 <= sim_distributions["sim_maker"] <= 1.0

    def test_calibration_parameter_bounds_validation(self):
        """Test that calibration parameters are within expected bounds."""
        test_params = {
            "latency_ms_mean": 200.0,
            "latency_ms_std": 100.0,
            "amend_latency_ms": 150.0,
            "cancel_latency_ms": 120.0,
            "toxic_sweep_prob": 0.20,
            "extra_slippage_bps": 4.0
        }
        
        from src.research.calibrate import DEFAULT_PARAM_BOUNDS, clamp_params
        
        # All parameters should be within default bounds
        clamped = clamp_params(test_params, DEFAULT_PARAM_BOUNDS)
        
        for param, value in test_params.items():
            bounds = DEFAULT_PARAM_BOUNDS[param]
            assert bounds[0] <= value <= bounds[1], f"Parameter {param}={value} outside bounds {bounds}"
            assert clamped[param] == value, f"Parameter {param} should not be clamped"
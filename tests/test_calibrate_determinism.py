"""
Tests for E2 Part 2/2 calibration determinism.
"""

import pytest
import json
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
import random
import numpy as np

from src.research.calibrate import (
    sample_candidates, params_hash, load_param_space, DEFAULT_PARAM_BOUNDS,
    clamp_params, select_best_candidate, round_floats
)


class TestCalibrateDeterminism:
    """Test determinism in E2 Part 2/2 calibration."""

    def test_sample_candidates_deterministic(self):
        """Test that candidate sampling is deterministic with same seed."""
        bounds = DEFAULT_PARAM_BOUNDS.copy()
        
        # Same parameters should produce identical candidates
        candidates1 = sample_candidates("random", 10, seed=42, bounds=bounds)
        candidates2 = sample_candidates("random", 10, seed=42, bounds=bounds)
        
        assert len(candidates1) == len(candidates2) == 10
        
        # Compare each candidate
        for i, (c1, c2) in enumerate(zip(candidates1, candidates2)):
            assert c1.keys() == c2.keys(), f"Candidate {i} has different parameter keys"
            for param in c1.keys():
                assert abs(c1[param] - c2[param]) < 1e-10, f"Candidate {i} param {param} differs: {c1[param]} vs {c2[param]}"

    def test_sample_candidates_different_seeds(self):
        """Test that different seeds produce different candidates."""
        bounds = DEFAULT_PARAM_BOUNDS.copy()
        
        candidates1 = sample_candidates("random", 5, seed=42, bounds=bounds)
        candidates2 = sample_candidates("random", 5, seed=123, bounds=bounds)
        
        # Should be different (with very high probability)
        any_different = False
        for c1, c2 in zip(candidates1, candidates2):
            for param in c1.keys():
                if abs(c1[param] - c2[param]) > 1e-6:
                    any_different = True
                    break
            if any_different:
                break
        
        assert any_different, "Different seeds should produce different candidates"

    def test_sample_candidates_with_baseline(self):
        """Test deterministic baseline neighborhood sampling."""
        bounds = DEFAULT_PARAM_BOUNDS.copy()
        baseline = {
            "latency_ms_mean": 200.0,
            "latency_ms_std": 100.0,
            "amend_latency_ms": 150.0,
            "cancel_latency_ms": 150.0,
            "toxic_sweep_prob": 0.1,
            "extra_slippage_bps": 3.0
        }
        
        # Should be deterministic with baseline
        candidates1 = sample_candidates("random", 15, seed=42, bounds=bounds, baseline_params=baseline)
        candidates2 = sample_candidates("random", 15, seed=42, bounds=bounds, baseline_params=baseline)
        
        assert len(candidates1) == len(candidates2) == 15
        
        # First ~12 candidates should be in baseline neighborhood (deterministic)
        for i in range(min(12, len(candidates1))):
            c1, c2 = candidates1[i], candidates2[i]
            for param in c1.keys():
                assert abs(c1[param] - c2[param]) < 1e-10, f"Baseline neighborhood candidate {i} differs"

    def test_grid_sampling_deterministic(self):
        """Test that grid sampling is deterministic."""
        bounds = DEFAULT_PARAM_BOUNDS.copy()
        
        candidates1 = sample_candidates("grid", 8, seed=42, bounds=bounds)
        candidates2 = sample_candidates("grid", 8, seed=123, bounds=bounds)  # Different seed
        
        # Grid should be identical regardless of seed
        assert len(candidates1) == len(candidates2) == 8
        
        for i, (c1, c2) in enumerate(zip(candidates1, candidates2)):
            for param in c1.keys():
                assert abs(c1[param] - c2[param]) < 1e-10, f"Grid candidate {i} differs with different seeds"

    def test_params_hash_deterministic(self):
        """Test that parameter hashing is deterministic."""
        params1 = {"a": 1.5, "b": 2.7, "c": 0.3}
        params2 = {"c": 0.3, "a": 1.5, "b": 2.7}  # Different order
        
        hash1 = params_hash(params1)
        hash2 = params_hash(params2)
        
        assert hash1 == hash2, "Hash should be identical regardless of parameter order"
        assert len(hash1) == 12, "Hash should be 12 characters"
        
        # Different parameters should have different hashes
        params3 = {"a": 1.6, "b": 2.7, "c": 0.3}  # Slightly different
        hash3 = params_hash(params3)
        assert hash1 != hash3, "Different parameters should have different hashes"

    def test_clamp_params_deterministic(self):
        """Test parameter clamping is deterministic."""
        bounds = {
            "param1": [0.0, 100.0],
            "param2": [10.0, 50.0],
            "param3": [0.0, 1.0]
        }
        
        # Out-of-bounds parameters
        params = {
            "param1": -10.0,  # Below min
            "param2": 75.0,   # Above max
            "param3": 0.5,    # Within bounds
            "param4": 999.0   # Not in bounds (should pass through)
        }
        
        clamped1 = clamp_params(params, bounds)
        clamped2 = clamp_params(params.copy(), bounds)
        
        assert clamped1 == clamped2, "Clamping should be deterministic"
        assert clamped1["param1"] == 0.0, "Should clamp to minimum"
        assert clamped1["param2"] == 50.0, "Should clamp to maximum"
        assert clamped1["param3"] == 0.5, "Should preserve in-bounds value"
        assert clamped1["param4"] == 999.0, "Should pass through unknown parameter"

    def test_candidate_selection_deterministic(self):
        """Test that best candidate selection is deterministic."""
        # Create mock evaluation results
        candidates = [
            {"param": 1.0},
            {"param": 2.0},
            {"param": 3.0}
        ]
        
        sim_results = [
            {"sim_hit": 0.25},
            {"sim_hit": 0.30},
            {"sim_hit": 0.28}
        ]
        
        loss_results = [
            {"TotalLoss": 0.5, "KS_queue": 0.2, "KS_bins": 0.1, "L_hit": 0.1, "L_maker": 0.1},
            {"TotalLoss": 0.3, "KS_queue": 0.1, "KS_bins": 0.1, "L_hit": 0.05, "L_maker": 0.05},  # Best
            {"TotalLoss": 0.4, "KS_queue": 0.15, "KS_bins": 0.12, "L_hit": 0.08, "L_maker": 0.05}
        ]
        
        evaluated = list(zip(candidates, sim_results, loss_results))
        
        # Selection should be deterministic
        best1 = select_best_candidate(evaluated)
        best2 = select_best_candidate(evaluated.copy())
        
        assert best1 == best2, "Best candidate selection should be deterministic"
        assert best1[0]["param"] == 2.0, "Should select candidate with lowest TotalLoss"

    def test_round_floats_deterministic(self):
        """Test that float rounding is deterministic."""
        data = {
            "float_val": 3.14159265359,
            "nested": {
                "array": [1.23456789, 2.34567890],
                "value": 9.87654321
            }
        }
        
        rounded1 = round_floats(data, dp=3)
        rounded2 = round_floats(data.copy(), dp=3)
        
        assert rounded1 == rounded2, "Float rounding should be deterministic"
        assert rounded1["float_val"] == 3.142
        assert rounded1["nested"]["array"] == [1.235, 2.346]
        assert rounded1["nested"]["value"] == 9.877

    def create_test_summary_files(self, symbol_dir: Path, symbol: str, count: int = 5):
        """Create deterministic test summary files."""
        base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        
        for i in range(count):
            hour = base_time + timedelta(hours=i)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            # Use deterministic data
            summary_data = {
                "schema_version": "e1.1",
                "symbol": symbol,
                "hour_utc": hour.strftime('%Y-%m-%dT%H:%M:%SZ'),
                "generated_at_utc": "2025-01-15T12:00:00.000000Z",  # Fixed for determinism
                "window_utc": {
                    "hour_start": hour.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "hour_end": (hour + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                "bins_max_bps": 25,
                "percentiles_used": [0.25, 0.5, 0.75, 0.9],
                "counts": {
                    "orders": 30 + i * 5,  # Deterministic progression
                    "quotes": 60 + i * 10,
                    "fills": 18 + i * 3
                },
                "hit_rate_by_bin": {
                    "0": {"count": 20 + i * 2, "fills": 6 + i},
                    "5": {"count": 20 + i * 3, "fills": 6 + i},
                    "10": {"count": 20 + i * 5, "fills": 6 + i}
                },
                "queue_wait_cdf_ms": [
                    {"p": 0.25, "v": 110.0 + i * 5},
                    {"p": 0.5, "v": 170.0 + i * 8},
                    {"p": 0.75, "v": 230.0 + i * 12},
                    {"p": 0.9, "v": 290.0 + i * 15}
                ],
                "metadata": {
                    "git_sha": f"deterministic_sha_{i:03d}",
                    "cfg_hash": f"deterministic_cfg_{i:03d}"
                }
            }
            
            with open(file_path, 'w') as f:
                json.dump(summary_data, f, indent=2, sort_keys=True)  # sort_keys for determinism

    @patch('src.research.calibrate.run_sim')
    def test_end_to_end_determinism(self, mock_run_sim, tmp_path):
        """Test that full E2 CLI produces identical results with same seed."""
        symbol = "DETERM"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir1 = tmp_path / "output1"
        out_dir2 = tmp_path / "output2"
        
        # Create identical test data
        self.create_test_summary_files(symbol_dir, symbol, count=15)
        
        # Mock deterministic simulation results
        def mock_sim_side_effect(candidate, symbol, out_dir, seed, bins_max_bps, percentiles, round_dp):
            # Return deterministic results based on candidate parameters
            param_sum = sum(candidate.values())
            return {
                "queue_wait_cdf_ms": [
                    {"p": 0.25, "v": 110.0 + param_sum * 0.1},
                    {"p": 0.5, "v": 170.0 + param_sum * 0.15},
                    {"p": 0.75, "v": 230.0 + param_sum * 0.2},
                    {"p": 0.9, "v": 290.0 + param_sum * 0.25}
                ],
                "hit_rate_by_bin": {
                    "0": {"count": 100, "fills": int(25 + param_sum * 0.01)},
                    "5": {"count": 100, "fills": int(23 + param_sum * 0.01)},
                    "10": {"count": 100, "fills": int(22 + param_sum * 0.01)}
                },
                "sim_hit": 0.23 + param_sum * 0.0001,
                "sim_maker": 0.20 + param_sum * 0.0001
            }
        
        mock_run_sim.side_effect = mock_sim_side_effect
        
        # Common CLI arguments
        base_cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T15:00:00Z",
            "--method", "random",
            "--trials", "5",
            "--seed", "12345",  # Same seed
            "--round-dp", "4",
            "--min-files", "3",
            "--min-total-count", "50"
        ]
        
        # Run 1
        cmd1 = base_cmd + ["--out", str(out_dir1)]
        result1 = subprocess.run(cmd1, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        
        # Run 2  
        cmd2 = base_cmd + ["--out", str(out_dir2)]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        
        assert result1.returncode == 0, f"First run should succeed: {result1.stderr}"
        assert result2.returncode == 0, f"Second run should succeed: {result2.stderr}"
        
        # Compare calibration.json files
        cal_path1 = out_dir1 / "calibration.json"
        cal_path2 = out_dir2 / "calibration.json"
        
        assert cal_path1.exists() and cal_path2.exists()
        
        with open(cal_path1, 'r') as f:
            cal_data1 = f.read()
        with open(cal_path2, 'r') as f:
            cal_data2 = f.read()
        
        assert cal_data1 == cal_data2, "Calibration files should be identical with same seed"
        
        # Compare key parts of report.json (metadata should be identical)
        report_path1 = out_dir1 / "report.json"
        report_path2 = out_dir2 / "report.json"
        
        with open(report_path1, 'r') as f:
            report1 = json.load(f)
        with open(report_path2, 'r') as f:
            report2 = json.load(f)
        
        # Calibration parameters should be identical
        assert report1["calibration_params"] == report2["calibration_params"]
        
        # Search metadata should be identical (except timestamps which might vary slightly)
        for key in ["method", "trials", "seed", "evaluated"]:
            assert report1["metadata"][key] == report2["metadata"][key], f"Metadata key {key} differs"

    def test_effective_w4_zero_when_missing(self):
        """Test that effective w4 is 0 when live_maker is None."""
        from src.research.calibrate import evaluate_candidate
        
        # Create LIVE distributions without live_maker
        live_distributions = {
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 200.0}],
            "hit_rate_by_bin": {"0": {"count": 100, "fills": 30}},
            "live_hit": 0.30,
            "live_maker": None  # Missing maker data
        }
        
        # Create SIM distributions
        sim_distributions = {
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 180.0}],
            "hit_rate_by_bin": {"0": {"count": 100, "fills": 25}},
            "sim_hit": 0.25,
            "sim_maker": 0.20
        }
        
        # Test with normal weights
        weights = {"KS_queue": 1.0, "KS_bins": 1.0, "L_hit": 1.0, "L_maker": 0.5, "L_reg": 1.0}
        candidate = {"latency_ms_mean": 100.0}
        
        loss_result = evaluate_candidate(
            candidate, live_distributions, weights, 
            reg_l2=0.0, baseline_params=None, sim_distributions=sim_distributions
        )
        
        assert loss_result is not None
        
        # Should have effective w4 = 0
        assert "w4_effective" in loss_result
        assert loss_result["w4_effective"] == 0.0, "w4_effective should be 0 when live_maker is None"
        
        # L_maker should be 0
        assert loss_result["L_maker"] == 0.0, "L_maker should be 0 when live_maker is None"
        
        # TotalLoss should not include L_maker contribution
        expected_total = (
            weights["KS_queue"] * loss_result["KS_queue"] +
            weights["KS_bins"] * loss_result["KS_bins"] +
            weights["L_hit"] * loss_result["L_hit"] +
            # No L_maker contribution
            weights["L_reg"] * loss_result["L_reg"]
        )
        
        assert abs(loss_result["TotalLoss"] - expected_total) < 1e-6, "TotalLoss should exclude L_maker when live_maker is None"
        
        # Test with live_maker present for comparison
        live_distributions_with_maker = live_distributions.copy()
        live_distributions_with_maker["live_maker"] = 0.28
        
        loss_result_with_maker = evaluate_candidate(
            candidate, live_distributions_with_maker, weights,
            reg_l2=0.0, baseline_params=None, sim_distributions=sim_distributions
        )
        
        assert loss_result_with_maker["w4_effective"] == 0.5, "w4_effective should be original weight when live_maker present"
        assert loss_result_with_maker["L_maker"] > 0.0, "L_maker should be > 0 when live_maker present"

    def test_same_seed_same_calibration_json(self, tmp_path):
        """Test that identical seed produces identical calibration.json and go_no_go metrics."""
        symbol = "DETERMINTEST"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        
        # Create test summary files
        self.create_test_summary_files(symbol_dir, symbol, count=8)
        
        seed = 12345
        out_dir1 = tmp_path / "run1"
        out_dir2 = tmp_path / "run2"
        
        # Run 1
        cmd1 = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T15:00:00Z",
            "--out", str(out_dir1),
            "--trials", "8",
            "--seed", str(seed),
            "--min-files", "3",
            "--min-total-count", "50"
        ]
        
        # Run 2 (identical)
        cmd2 = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T15:00:00Z",
            "--out", str(out_dir2),
            "--trials", "8",
            "--seed", str(seed),
            "--min-files", "3",
            "--min-total-count", "50"
        ]
        
        # Execute both runs
        result1 = subprocess.run(cmd1, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        result2 = subprocess.run(cmd2, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        
        assert result1.returncode == 0, f"Run 1 should succeed, got: {result1.stderr}"
        assert result2.returncode == 0, f"Run 2 should succeed, got: {result2.stderr}"
        
        # Read calibration.json files
        calib1_path = out_dir1 / "calibration.json"
        calib2_path = out_dir2 / "calibration.json"
        
        assert calib1_path.exists() and calib2_path.exists()
        
        with open(calib1_path, 'r') as f:
            calib1 = f.read()
        with open(calib2_path, 'r') as f:
            calib2 = f.read()
        
        # calibration.json should be byte-for-byte identical
        assert calib1 == calib2, "calibration.json files should be identical for same seed"
        
        # Read report.json files
        report1_path = out_dir1 / "report.json"
        report2_path = out_dir2 / "report.json"
        
        assert report1_path.exists() and report2_path.exists()
        
        with open(report1_path, 'r') as f:
            report1 = json.load(f)
        with open(report2_path, 'r') as f:
            report2 = json.load(f)
        
        # go_no_go metrics should be identical for key numerical fields
        gng1 = report1.get("go_no_go", {})
        gng2 = report2.get("go_no_go", {})
        
        assert gng1 and gng2, "Both reports should have go_no_go blocks"
        
        # Key numerical metrics should be identical
        numerical_fields = ["ks_queue_after", "ks_bins_after", "w4_effective", 
                           "sim_live_divergence", "loss_before", "loss_after"]
        for field in numerical_fields:
            assert gng1[field] == gng2[field], f"go_no_go.{field} should be identical across runs"
        
        # Boolean field should also match
        assert gng1["loss_regressed"] == gng2["loss_regressed"], "loss_regressed should be identical"
        
        # Calibration parameters should be identical
        assert report1["calibration_params"] == report2["calibration_params"], "Calibration parameters should be identical"

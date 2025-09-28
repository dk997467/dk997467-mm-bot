"""
Tests for E2 Part 2/2 calibration CLI.
"""

import pytest
import json
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestCalibrateE2CLI:
    """Test E2 Part 2/2 CLI functionality."""

    def create_test_summary_files(self, symbol_dir: Path, symbol: str, count: int = 5) -> list:
        """Create test summary files for CLI testing."""
        base_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        created_files = []
        
        for i in range(count):
            hour = base_time + timedelta(hours=i)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            summary_data = {
                "schema_version": "e1.1",
                "symbol": symbol,
                "hour_utc": hour.strftime('%Y-%m-%dT%H:%M:%SZ'),
                "generated_at_utc": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                "window_utc": {
                    "hour_start": hour.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "hour_end": (hour + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                "bins_max_bps": 25,
                "percentiles_used": [0.25, 0.5, 0.75, 0.9],
                "counts": {
                    "orders": 30 + i * 6,
                    "quotes": 60 + i * 12,
                    "fills": 18 + i * 3
                },
                "hit_rate_by_bin": {
                    "0": {"count": 20 + i * 3, "fills": 6 + i},
                    "5": {"count": 20 + i * 4, "fills": 6 + i},
                    "10": {"count": 20 + i * 5, "fills": 6 + i}
                },
                "queue_wait_cdf_ms": [
                    {"p": 0.25, "v": 110.0 + i * 8},
                    {"p": 0.5, "v": 170.0 + i * 12},
                    {"p": 0.75, "v": 230.0 + i * 16},
                    {"p": 0.9, "v": 290.0 + i * 20}
                ],
                "metadata": {
                    "git_sha": f"test_sha_{i}",
                    "cfg_hash": f"test_cfg_{i}"
                }
            }
            
            with open(file_path, 'w') as f:
                json.dump(summary_data, f, indent=2, sort_keys=True)
            
            created_files.append((hour, file_path))
        
        return created_files

    @patch('src.research.calibrate.run_sim')
    def test_e2_parameter_search_basic(self, mock_run_sim, tmp_path):
        """Test basic E2 parameter search functionality."""
        symbol = "E2BASIC"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create test summary files
        self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        # Mock simulation results
        mock_sim_distributions = {
            "queue_wait_cdf_ms": [
                {"p": 0.25, "v": 115.0},
                {"p": 0.5, "v": 175.0},
                {"p": 0.75, "v": 235.0},
                {"p": 0.9, "v": 295.0}
            ],
            "hit_rate_by_bin": {
                "0": {"count": 100, "fills": 28},
                "5": {"count": 100, "fills": 26},
                "10": {"count": 100, "fills": 24}
            },
            "sim_hit": 0.26,
            "sim_maker": 0.22
        }
        mock_run_sim.return_value = mock_sim_distributions
        
        # Run CLI with parameter search
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T15:00:00Z",
            "--out", str(out_dir),
            "--method", "random",
            "--trials", "5",  # Small number for fast testing
            "--seed", "42",
            "--min-files", "3",
            "--min-total-count", "50"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        
        if result.returncode != 0:
            print(f"CLI failed with stdout: {result.stdout}")
            print(f"CLI failed with stderr: {result.stderr}")
        
        assert result.returncode == 0, f"CLI should succeed, got: {result.stderr}"
        
        # Check that E2 artifacts were created
        calibration_path = out_dir / "calibration.json"
        report_path = out_dir / "report.json"
        report_md_path = out_dir / "REPORT.md"
        
        assert calibration_path.exists(), "calibration.json should be created"
        assert report_path.exists(), "report.json should be created"
        assert report_md_path.exists(), "REPORT.md should be created"
        
        # Validate calibration.json structure
        with open(calibration_path, 'r') as f:
            calibration_data = json.load(f)
        
        expected_params = {"latency_ms_mean", "latency_ms_std", "amend_latency_ms", 
                          "cancel_latency_ms", "toxic_sweep_prob", "extra_slippage_bps"}
        assert set(calibration_data.keys()) == expected_params, f"Missing calibration parameters"
        
        # All parameters should be within bounds
        for param, value in calibration_data.items():
            assert isinstance(value, (int, float)), f"Parameter {param} should be numeric"
            assert 0.0 <= value <= 1000.0, f"Parameter {param} seems out of reasonable bounds"
        
        # Validate report.json structure
        with open(report_path, 'r') as f:
            report_data = json.load(f)
        
        required_keys = {"metadata", "calibration_params", "live_distributions", 
                        "sim_after", "loss_after"}
        assert all(key in report_data for key in required_keys), f"Missing report keys"
        
        # Check search metadata
        metadata = report_data["metadata"]
        assert metadata["method"] == "random"
        assert metadata["trials"] == 5
        assert metadata["seed"] == 42
        assert metadata["evaluated"] >= 1  # At least one candidate should be evaluated
        
        # Check loss improvement (mock should be close to live)
        loss_after = report_data["loss_after"]
        assert "TotalLoss" in loss_after
        assert loss_after["TotalLoss"] >= 0.0
        
        # Validate REPORT.md content
        with open(report_md_path, 'r') as f:
            report_content = f.read()
        
        assert "# Calibration Report" in report_content
        assert "Search Summary" in report_content
        assert "Selected Parameters" in report_content
        assert "Performance Comparison" in report_content
        assert "Units & Notes" in report_content

    @patch('src.research.calibrate.run_sim')
    def test_e2_with_baseline_parameters(self, mock_run_sim, tmp_path):
        """Test E2 search with baseline parameters."""
        symbol = "E2BASELINE"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create test summary files
        self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        # Create baseline calibration file
        baseline_params = {
            "latency_ms_mean": 150.0,
            "latency_ms_std": 75.0,
            "amend_latency_ms": 120.0,
            "cancel_latency_ms": 100.0,
            "toxic_sweep_prob": 0.15,
            "extra_slippage_bps": 2.5
        }
        
        baseline_path = tmp_path / "baseline.json"
        with open(baseline_path, 'w') as f:
            json.dump(baseline_params, f)
        
        # Mock simulation results (should be different from baseline)
        mock_sim_distributions = {
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 160.0}],
            "hit_rate_by_bin": {"0": {"count": 100, "fills": 30}},
            "sim_hit": 0.30,
            "sim_maker": 0.25
        }
        mock_run_sim.return_value = mock_sim_distributions
        
        # Run CLI with baseline
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T15:00:00Z",
            "--out", str(out_dir),
            "--baseline", str(baseline_path),
            "--trials", "3",
            "--seed", "123",
            "--min-files", "3",
            "--min-total-count", "50"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, f"CLI with baseline should succeed, got: {result.stderr}"
        
        # Check that baseline was used
        report_path = out_dir / "report.json"
        with open(report_path, 'r') as f:
            report_data = json.load(f)
        
        assert report_data["baseline_params"] == baseline_params
        assert "Loaded baseline parameters" in result.stdout

    @patch('src.research.calibrate.run_sim')
    def test_e2_custom_weights(self, mock_run_sim, tmp_path):
        """Test E2 search with custom loss weights."""
        symbol = "E2WEIGHTS"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create test summary files
        self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        # Mock simulation
        mock_sim_distributions = {
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 160.0}],
            "hit_rate_by_bin": {"0": {"count": 100, "fills": 30}},
            "sim_hit": 0.30,
            "sim_maker": 0.25
        }
        mock_run_sim.return_value = mock_sim_distributions
        
        # Run CLI with custom weights
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T15:00:00Z",
            "--out", str(out_dir),
            "--weights", "2.0", "1.5", "0.8", "0.3",  # Custom weights
            "--reg-l2", "0.01",
            "--trials", "3",
            "--seed", "456",
            "--min-files", "3",
            "--min-total-count", "50"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, f"CLI with custom weights should succeed, got: {result.stderr}"
        
        # Check weights were applied
        report_path = out_dir / "report.json"
        with open(report_path, 'r') as f:
            report_data = json.load(f)
        
        weights = report_data["metadata"]["weights"]
        assert weights["KS_queue"] == 2.0
        assert weights["KS_bins"] == 1.5
        assert weights["L_hit"] == 0.8
        assert weights["L_maker"] == 0.3
        
        assert report_data["metadata"]["reg_l2"] == 0.01

    def test_e2_part1_fallback_without_trials(self, tmp_path):
        """Test that CLI falls back to E2 Part 1 mode when appropriate."""
        symbol = "E2FALLBACK"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create test summary files
        self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        # Run CLI in Part 1 mode (no --trials specified should not trigger Part 2/2)
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T15:00:00Z",
            "--out", str(out_dir),
            # No search parameters - should stay in Part 1 mode
            "--seed", "789",
            "--min-files", "3",
            "--min-total-count", "50"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, f"Part 1 fallback should succeed, got: {result.stderr}"
        
        # Should create Part 1 outputs, not Part 2/2
        live_dist_path = out_dir / "live_distributions.json"
        report_core_path = out_dir / "REPORT_core.md"
        
        assert live_dist_path.exists(), "live_distributions.json should be created"
        assert report_core_path.exists(), "REPORT_core.md should be created"
        
        # Should NOT create Part 2/2 outputs
        calibration_path = out_dir / "calibration.json"
        assert not calibration_path.exists(), "calibration.json should NOT be created in Part 1 mode"
        
        # Output should indicate Part 1 mode
        assert "Starting parameter search" not in result.stdout
        assert "E2 calibration completed successfully" in result.stdout

    @patch('src.research.calibrate.run_sim')
    def test_cache_and_early_stop_metadata(self, mock_run_sim, tmp_path):
        """Test cache statistics and early stop metadata in reports."""
        symbol = "CACHETEST"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create test summary files
        self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        # Mock simulation - return same result for duplicate candidates (cache test)
        mock_sim_distributions = {
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 150.0}],
            "hit_rate_by_bin": {"0": {"count": 100, "fills": 25}},
            "sim_hit": 0.25,
            "sim_maker": None  # Test missing maker scenario
        }
        
        # Return identical results to test caching
        mock_run_sim.return_value = mock_sim_distributions
        
        # Run CLI with early stop
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T15:00:00Z",
            "--out", str(out_dir),
            "--trials", "15",  # More trials to test progress
            "--max-secs", "1",  # Very short time limit to trigger early stop
            "--seed", "999",
            "--min-files", "3",
            "--min-total-count", "50"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, f"CLI should succeed, got: {result.stderr}"
        
        # Check that progress logs appeared
        assert "Progress:" in result.stdout, "Should show progress logs"
        
        # Check early stop message
        assert "Early stop" in result.stdout, "Should show early stop message"
        
        # Check report.json contains cache and early stop metadata
        report_path = out_dir / "report.json"
        assert report_path.exists()
        
        with open(report_path, 'r') as f:
            report_data = json.load(f)
        
        metadata = report_data["metadata"]
        
        # Should have cache statistics
        assert "cache_hits" in metadata
        assert "cache_misses" in metadata
        assert isinstance(metadata["cache_hits"], int)
        assert isinstance(metadata["cache_misses"], int)
        
        # Should have early stop info
        assert "stopped_early" in metadata
        assert metadata["stopped_early"] == True, "Should be stopped early due to time limit"
        
        # Should have effective w4 = 0 due to missing live_maker
        assert "w4_effective" in metadata
        assert metadata["w4_effective"] == 0.0, "w4_effective should be 0 when live_maker is None"
        
        # Check REPORT.md contains cache and early stop info
        report_md_path = out_dir / "REPORT.md"
        assert report_md_path.exists()
        
        with open(report_md_path, 'r') as f:
            report_content = f.read()
        
        # Should mention cache statistics
        assert "Cache:" in report_content
        assert "hits" in report_content and "misses" in report_content
        
        # Should mention early stopping
        assert "Stopped early: true" in report_content
        assert "Early Stop Details" in report_content
        
        # Should mention effective w4
        assert "effective: 0" in report_content or "effective: 0.0" in report_content


class TestCalibrateGoNoGo:
    """Test Go/No-Go checks in calibration."""
    
    def create_test_summary_files(self, symbol_dir: Path, symbol: str, count: int = 5) -> None:
        """Create test summary files for calibration."""
        for i in range(count):
            hour = 10 + i
            filename = f"{symbol}_2025-01-15_{hour:02d}.json"
            file_path = symbol_dir / filename
            
            summary = {
                "schema_version": "e1.1",
                "symbol": symbol,
                "hour_utc": f"2025-01-15T{hour:02d}:00:00Z",
                "generated_at_utc": "2025-01-15T16:00:00Z",
                "window_utc": {
                    "hour_start": f"2025-01-15T{hour:02d}:00:00Z",
                    "hour_end": f"2025-01-15T{hour+1:02d}:00:00Z"
                },
                "bins_max_bps": 50,
                "percentiles_used": [0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99],
                "counts": {
                    "orders": 150 + i * 10,
                    "quotes": 130 + i * 8,
                    "fills": 40 + i * 5
                },
                "hit_rate_by_bin": {
                    "0": {"count": 80 + i * 5, "fills": 25 + i * 2},
                    "5": {"count": 45 + i * 3, "fills": 10 + i},
                    "10": {"count": 25 + i * 2, "fills": 5 + i}
                },
                "queue_wait_cdf_ms": [
                    {"p": 0.25, "v": 120.0 + i * 5},
                    {"p": 0.5, "v": 180.0 + i * 8},
                    {"p": 0.75, "v": 240.0 + i * 10},
                    {"p": 0.9, "v": 300.0 + i * 12}
                ],
                "metadata": {
                    "git_sha": "test_sha",
                    "cfg_hash": "test_hash"
                }
            }
            
            with open(file_path, 'w') as f:
                json.dump(summary, f, indent=2)

    @patch('src.research.calibrate.run_sim')
    def test_go_no_go_metrics_in_report(self, mock_run_sim, tmp_path):
        """Test Go/No-Go metrics are correctly calculated and included in reports."""
        symbol = "GNGTEST"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create test summary files
        self.create_test_summary_files(symbol_dir, symbol, count=10)
        
        # Mock simulation with specific KS values for testing clamp
        mock_sim_distributions = {
            "queue_wait_cdf_ms": [{"p": 0.5, "v": 200.0}],
            "hit_rate_by_bin": {"0": {"count": 100, "fills": 30}},
            "sim_hit": 0.30,
            "sim_maker": None  # Test missing maker scenario
        }
        
        mock_run_sim.return_value = mock_sim_distributions
        
        # Run CLI 
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T15:00:00Z",
            "--out", str(out_dir),
            "--trials", "5",
            "--seed", "777",
            "--min-files", "3",
            "--min-total-count", "50"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, f"CLI should succeed, got: {result.stderr}"
        
        # Check report.json contains go_no_go block
        report_path = out_dir / "report.json"
        assert report_path.exists()
        
        with open(report_path, 'r') as f:
            report_data = json.load(f)
        
        # Should have go_no_go block
        assert "go_no_go" in report_data, "report.json should contain go_no_go block"
        go_no_go = report_data["go_no_go"]
        
        # Check required fields
        required_fields = ["ks_queue_after", "ks_bins_after", "w4_effective", 
                          "sim_live_divergence", "loss_before", "loss_after", "loss_regressed"]
        for field in required_fields:
            assert field in go_no_go, f"go_no_go should contain {field}"
        
        # KS values should be in [0,1] range
        assert 0.0 <= go_no_go["ks_queue_after"] <= 1.0, "ks_queue_after should be in [0,1]"
        assert 0.0 <= go_no_go["ks_bins_after"] <= 1.0, "ks_bins_after should be in [0,1]"
        
        # sim_live_divergence should be 0.5 * (ks_queue + ks_bins)
        expected_divergence = 0.5 * (go_no_go["ks_queue_after"] + go_no_go["ks_bins_after"])
        assert abs(go_no_go["sim_live_divergence"] - expected_divergence) < 1e-9, "sim_live_divergence should be 0.5*(ks_queue+ks_bins)"
        
        # w4_effective should be 0 when live_maker is None
        assert go_no_go["w4_effective"] == 0.0, "w4_effective should be 0 when live_maker is None"
        
        # loss_regressed should be boolean
        assert isinstance(go_no_go["loss_regressed"], bool), "loss_regressed should be boolean"
        
        # Check REPORT.md contains Go/No-Go section
        report_md_path = out_dir / "REPORT.md"
        assert report_md_path.exists()
        
        with open(report_md_path, 'r') as f:
            report_content = f.read()
        
        # Should have Go/No-Go section
        assert "## Go/No-Go" in report_content, "REPORT.md should contain Go/No-Go section"
        assert "KS (after):" in report_content, "Should show KS after values"
        assert "sim_live_divergence:" in report_content, "Should show sim_live_divergence"
        assert "w4_effective:" in report_content, "Should show w4_effective"
        assert "loss_before → loss_after:" in report_content, "Should show loss progression"

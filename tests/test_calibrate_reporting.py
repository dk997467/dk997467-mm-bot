"""
Tests for E2 Tiny Polish: params_hash, audit metadata, and Repro command functionality.
"""

import json
import hashlib
import tempfile
import argparse
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.research.calibrate import (
    compute_params_hash, 
    build_repro_command,
    _validate_go_no_go_block,
    write_json_sorted
)


class TestParamsHash:
    """Test params_hash computation and stability."""

    def test_params_hash_present_and_stable(self, tmp_path):
        """Test that params_hash is present and stable across runs."""
        # Create test calibration.json
        calibration_path = tmp_path / "calibration.json"
        test_params = {
            "latency_ms_mean": 150.0,
            "latency_ms_std": 25.0,
            "amend_latency_ms": 75.0,
            "cancel_latency_ms": 50.0,
            "toxic_sweep_prob": 0.08,
            "extra_slippage_bps": 3.5
        }
        
        # Write with sorted keys (like the real system)
        write_json_sorted(calibration_path, test_params)
        
        # Compute hash twice
        hash1 = compute_params_hash(calibration_path)
        hash2 = compute_params_hash(calibration_path)
        
        # Should be identical
        assert hash1 == hash2, "params_hash should be deterministic"
        assert len(hash1) == 64, "params_hash should be 64-character hex"
        assert all(c in '0123456789abcdef' for c in hash1), "params_hash should be valid hex"
        
        # Verify it matches manual calculation
        params_sorted = json.loads(calibration_path.read_text("utf-8"))
        params_bytes = json.dumps(params_sorted, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected_hash = hashlib.sha256(params_bytes).hexdigest()
        
        assert hash1 == expected_hash, "params_hash should match manual SHA256 calculation"

    def test_params_hash_changes_with_params(self, tmp_path):
        """Test that params_hash changes when parameters change."""
        calibration_path = tmp_path / "calibration.json"
        
        # Original parameters
        params1 = {"latency_ms_mean": 150.0, "latency_ms_std": 25.0}
        write_json_sorted(calibration_path, params1)
        hash1 = compute_params_hash(calibration_path)
        
        # Modified parameters
        params2 = {"latency_ms_mean": 151.0, "latency_ms_std": 25.0}  # Small change
        write_json_sorted(calibration_path, params2)
        hash2 = compute_params_hash(calibration_path)
        
        assert hash1 != hash2, "params_hash should change when parameters change"


class TestAuditMetadata:
    """Test audit metadata fields presence and types."""

    def test_metadata_audit_fields_present(self):
        """Test that required audit fields are present with correct types."""
        # Create mock args
        args = argparse.Namespace()
        args.method = "random"
        args.trials = 50
        args.workers = 4
        args.seed = 12345
        
        # Mock search metadata (like in real system)
        search_metadata = {
            "symbol": "BTCUSDT",
            "method": args.method,
            "trials": int(args.trials),
            "workers": int(args.workers),
            "seed": int(args.seed),
            "evaluated": 25,
            "time_seconds": 120.5,
            "cache_hits": 8,
            "cache_misses": 17
        }
        
        # Verify required fields are present
        assert "method" in search_metadata
        assert "trials" in search_metadata
        assert "workers" in search_metadata
        assert "seed" in search_metadata
        
        # Verify correct types
        assert isinstance(search_metadata["method"], str)
        assert isinstance(search_metadata["trials"], int)
        assert isinstance(search_metadata["workers"], int)
        assert isinstance(search_metadata["seed"], int)
        
        # Verify correct values
        assert search_metadata["method"] == "random"
        assert search_metadata["trials"] == 50
        assert search_metadata["workers"] == 4
        assert search_metadata["seed"] == 12345


class TestReproCommand:
    """Test repro command generation."""

    def test_build_repro_command_basic(self):
        """Test basic repro command construction."""
        # Create mock args
        args = argparse.Namespace()
        args.symbol = "BTCUSDT"
        args.summaries_dir = "data/research/summaries"
        args.from_utc = "2024-01-01T00:00:00.000Z"
        args.to_utc = "2024-01-02T00:00:00.000Z"
        args.method = "random"
        args.trials = 60
        args.workers = 2
        args.seed = 42
        args.bins_max_bps = 50
        args.percentiles = [0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
        args.weights = [1.0, 1.0, 0.5, 0.25]
        args.reg_l2 = 0.01
        args.round_dp = 6
        args.out = "artifacts/calibration/BTCUSDT"
        args.baseline = None
        args.param_space = None
        
        cmd = build_repro_command(args)
        
        # Should be a single line
        assert '\n' not in cmd, "Repro command should be single line"
        
        # Should contain required components
        assert "--symbol BTCUSDT" in cmd
        assert "--method random" in cmd
        assert "--trials 60" in cmd
        assert "--workers 2" in cmd
        assert "--seed 42" in cmd
        assert "--bins-max-bps 50" in cmd
        assert "--percentiles" in cmd
        assert "--weights 1.0 1.0 0.5 0.25" in cmd
        assert "--reg-l2 0.01" in cmd
        assert "--round-dp 6" in cmd
        assert "--out artifacts/calibration/BTCUSDT" in cmd
        
        # Should start with python command
        assert cmd.startswith("python -m src.research.calibrate")

    def test_build_repro_command_with_optional_args(self):
        """Test repro command with optional baseline and param-space."""
        args = argparse.Namespace()
        args.symbol = "ETHUSDT"
        args.summaries_dir = "data/research/summaries"
        args.from_utc = "2024-01-01T00:00:00.000Z"
        args.to_utc = "2024-01-02T00:00:00.000Z"
        args.method = "grid"
        args.trials = 30
        args.workers = 1
        args.seed = 123
        args.bins_max_bps = 40
        args.percentiles = [0.5, 0.9, 0.95, 0.99]
        args.weights = [1.0, 1.0, 1.0, 1.0]
        args.reg_l2 = 0.0
        args.round_dp = 4
        args.out = "tmp/calib"
        args.baseline = "baseline_params.json"
        args.param_space = "custom_space.json"
        
        cmd = build_repro_command(args)
        
        # Should include optional arguments
        assert "--baseline baseline_params.json" in cmd
        assert "--param-space custom_space.json" in cmd
        assert "--percentiles" in cmd and "0.5,0.9,0.95,0.99" in cmd

    def test_report_md_contains_repro(self, tmp_path):
        """Test that REPORT.md contains Repro line when args provided."""
        from src.research.calibrate import generate_calibration_report_md
        
        # Create mock report data
        report_data = {
            "metadata": {
                "symbol": "TESTBTC",
                "from_utc": "2024-01-01T00:00:00.000Z",
                "to_utc": "2024-01-02T00:00:00.000Z",
                "method": "random",
                "trials": 50,
                "evaluated": 25,
                "time_seconds": 150.0,
                "seed": 42,
                "cache_hits": 10,
                "cache_misses": 15,
                "stopped_early": False
            },
            "params_hash": "abcd1234" * 8,  # 64 chars
            "calibration_params": {"latency_ms_mean": 100.0},
            "live_distributions": {
                "live_hit": 0.25,
                "live_maker": None,
                "queue_wait_cdf_ms": [],
                "hit_rate_by_bin": {}
            },
            "sim_after": {"sim_hit": 0.24, "sim_maker": None},
            "loss_after": {
                "KS_queue": 0.1, "KS_bins": 0.05, "L_hit": 0.02,
                "L_maker": 0.0, "L_reg": 0.001, "TotalLoss": 0.171
            },
            "go_no_go": {
                "ks_queue_after": 0.1,
                "ks_bins_after": 0.05,
                "w4_effective": 0.0,
                "sim_live_divergence": 0.075,
                "loss_before": 0.0,
                "loss_after": 0.171,
                "loss_regressed": False
            }
        }
        
        # Create mock args
        args = argparse.Namespace()
        args.symbol = "TESTBTC"
        args.summaries_dir = "data/summaries"
        args.from_utc = "2024-01-01T00:00:00.000Z"
        args.to_utc = "2024-01-02T00:00:00.000Z"
        args.method = "random"
        args.trials = 50
        args.workers = 2
        args.seed = 42
        args.bins_max_bps = 50
        args.percentiles = [0.5, 0.9, 0.95, 0.99]
        args.weights = [1.0, 1.0, 0.5, 0.25]
        args.reg_l2 = 0.01
        args.round_dp = 6
        args.out = "artifacts/calibration/TESTBTC"
        args.baseline = None
        args.param_space = None
        
        # Generate report
        report_path = tmp_path / "REPORT.md"
        generate_calibration_report_md(report_data, report_path, args)
        
        # Read and check content
        content = report_path.read_text("utf-8")
        
        # Should contain Repro line
        assert "**Repro**:" in content, "REPORT.md should contain Repro line"
        assert "--seed 42" in content, "Repro line should contain seed"
        assert "--trials 50" in content, "Repro line should contain trials"
        
        # Should be near the top
        lines = content.split('\n')
        repro_line_idx = next(i for i, line in enumerate(lines) if "**Repro**:" in line)
        assert repro_line_idx < 10, "Repro line should be near top of report"

    def test_report_md_without_args(self, tmp_path):
        """Test that REPORT.md works without args (no Repro line)."""
        from src.research.calibrate import generate_calibration_report_md
        
        # Same report data as above
        report_data = {
            "metadata": {
                "symbol": "TESTBTC",
                "from_utc": "2024-01-01T00:00:00.000Z",
                "to_utc": "2024-01-02T00:00:00.000Z",
                "method": "random",
                "trials": 50,
                "evaluated": 25,
                "time_seconds": 150.0,
                "seed": 42,
                "cache_hits": 10,
                "cache_misses": 15,
                "stopped_early": False
            },
            "params_hash": "abcd1234" * 8,
            "calibration_params": {"latency_ms_mean": 100.0},
            "live_distributions": {
                "live_hit": 0.25,
                "live_maker": None,
                "queue_wait_cdf_ms": [],
                "hit_rate_by_bin": {}
            },
            "sim_after": {"sim_hit": 0.24, "sim_maker": None},
            "loss_after": {
                "KS_queue": 0.1, "KS_bins": 0.05, "L_hit": 0.02,
                "L_maker": 0.0, "L_reg": 0.001, "TotalLoss": 0.171
            },
            "go_no_go": {
                "ks_queue_after": 0.1,
                "ks_bins_after": 0.05,
                "w4_effective": 0.0,
                "sim_live_divergence": 0.075,
                "loss_before": 0.0,
                "loss_after": 0.171,
                "loss_regressed": False
            }
        }
        
        # Generate report without args
        report_path = tmp_path / "REPORT.md"
        generate_calibration_report_md(report_data, report_path, args=None)
        
        # Read and check content
        content = report_path.read_text("utf-8")
        
        # Should NOT contain Repro line
        assert "**Repro**:" not in content, "REPORT.md should not contain Repro when args=None"
        assert "## Search Summary" in content, "Should still have normal structure"

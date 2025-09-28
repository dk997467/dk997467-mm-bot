"""
Tests for E2 Part 1 calibration CLI skeleton.
"""

import pytest
import json
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestCalibrateCLISkeleton:
    """Test CLI skeleton functionality for E2 Part 1."""

    def create_test_summary_files(self, symbol_dir: Path, symbol: str, count: int = 3) -> list:
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
                "hour_utc": hour.isoformat() + "Z",
                "generated_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
                "window_utc": {
                    "hour_start": hour.isoformat() + "Z",
                    "hour_end": (hour + timedelta(hours=1)).isoformat() + "Z"
                },
                "bins_max_bps": 50,
                "percentiles_used": [0.25, 0.5, 0.75, 0.9],
                "counts": {
                    "orders": 20 + i * 5,
                    "quotes": 40 + i * 10,
                    "fills": 10 + i * 2
                },
                "hit_rate_by_bin": {
                    "0": {"count": 15 + i * 3, "fills": 4 + i},
                    "5": {"count": 12 + i * 3, "fills": 3 + i},
                    "10": {"count": 13 + i * 4, "fills": 3 + i}
                },
                "queue_wait_cdf_ms": [
                    {"p": 0.25, "v": 100.0 + i * 10},
                    {"p": 0.5, "v": 150.0 + i * 15},
                    {"p": 0.75, "v": 200.0 + i * 20},
                    {"p": 0.9, "v": 250.0 + i * 25}
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

    def create_sim_fixture(self, out_dir: Path) -> Path:
        """Create a SIM fixture file for testing loss calculation."""
        sim_fixture = {
            "queue_wait_cdf_ms": [
                {"p": 0.25, "v": 95.0},
                {"p": 0.5, "v": 145.0},
                {"p": 0.75, "v": 195.0},
                {"p": 0.9, "v": 245.0}
            ],
            "hit_rate_by_bin": {
                "0": {"count": 50, "fills": 12},
                "5": {"count": 45, "fills": 11},
                "10": {"count": 48, "fills": 10}
            },
            "sim_hit": 0.235,
            "sim_maker": 0.188
        }
        
        sim_path = out_dir / "sim_fixture.json"
        with open(sim_path, 'w') as f:
            json.dump(sim_fixture, f, indent=2, sort_keys=True)
        
        return sim_path

    def test_cli_creates_live_distributions_json(self, tmp_path):
        """Test that CLI creates live_distributions.json."""
        symbol = "CLITEST"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create test summary files with sufficient data
        files_created = self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        # Run CLI
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T13:00:00Z",
            "--out", str(out_dir),
            "--bins-max-bps", "20",
            "--percentiles", "0.25,0.5,0.75,0.9",
            "--seed", "42",
            "--round-dp", "4",
            "--min-files", "3",  # Lower threshold for test
            "--min-total-count", "30"  # Lower threshold for test
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        
        if result.returncode != 0:
            print(f"CLI failed with stdout: {result.stdout}")
            print(f"CLI failed with stderr: {result.stderr}")
        
        assert result.returncode == 0, f"CLI should succeed, got: {result.stderr}"
        
        # Check that live_distributions.json was created
        live_dist_path = out_dir / "live_distributions.json"
        assert live_dist_path.exists(), "live_distributions.json should be created"
        
        # Validate content
        with open(live_dist_path, 'r') as f:
            live_data = json.load(f)
        
        assert "live_hit" in live_data
        assert "live_maker" in live_data
        assert "queue_wait_cdf_ms" in live_data
        assert "hit_rate_by_bin" in live_data
        
        # Check that percentiles match
        cdf = live_data["queue_wait_cdf_ms"]
        cdf_percentiles = [entry["p"] for entry in cdf]
        assert 0.25 in cdf_percentiles
        assert 0.5 in cdf_percentiles
        assert 0.75 in cdf_percentiles
        assert 0.9 in cdf_percentiles
        
        # Check that bins go up to max_bps
        bins = live_data["hit_rate_by_bin"]
        assert "0" in bins
        assert "20" in bins  # Should have bin up to max_bps
        
        # Check REPORT_core.md was created
        report_path = out_dir / "REPORT_core.md"
        assert report_path.exists(), "REPORT_core.md should be created"
        
        with open(report_path, 'r') as f:
            report_content = f.read()
        
        assert "CLITEST" in report_content
        assert "LIVE Distributions" in report_content
        assert "Queue Wait CDF" in report_content
        assert "Hit Rate by Price Bin" in report_content

    def test_cli_with_sim_fixture_creates_loss_analysis(self, tmp_path):
        """Test that CLI creates loss analysis when SIM fixture is present."""
        symbol = "LOSSTEST"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        
        # Create test summary files
        self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        # Create SIM fixture
        sim_path = self.create_sim_fixture(out_dir)
        assert sim_path.exists()
        
        # Run CLI
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z", 
            "--to-utc", "2025-01-15T13:00:00Z",
            "--out", str(out_dir),
            "--min-files", "3",
            "--min-total-count", "30"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        
        assert result.returncode == 0, f"CLI should succeed, got: {result.stderr}"
        
        # Check that report_core.json was created
        report_core_path = out_dir / "report_core.json"
        assert report_core_path.exists(), "report_core.json should be created when SIM fixture exists"
        
        # Validate loss analysis content
        with open(report_core_path, 'r') as f:
            report_data = json.load(f)
        
        assert "metadata" in report_data
        assert "live_distributions" in report_data  
        assert "sim_distributions" in report_data
        assert "loss_components" in report_data
        
        loss = report_data["loss_components"]
        assert "TotalLoss" in loss
        assert "KS_queue" in loss
        assert "KS_bins" in loss
        assert "L_hit" in loss
        assert "L_maker" in loss
        assert "L_reg" in loss
        
        # Check that REPORT_core.md includes loss analysis
        report_md_path = out_dir / "REPORT_core.md"
        with open(report_md_path, 'r') as f:
            report_content = f.read()
        
        assert "Loss Analysis" in report_content
        assert "Total Loss" in report_content
        assert "SIM Distributions" in report_content

    def test_cli_default_timestamps(self, tmp_path):
        """Test CLI with default timestamps (now-24h to now)."""
        symbol = "TIMETEST"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create test files for recent hours
        now = datetime.now(timezone.utc)
        for i in range(25, 5, -1):  # 25 hours ago to 5 hours ago
            hour = now - timedelta(hours=i)
            filename = f"{symbol}_{hour.strftime('%Y-%m-%d_%H')}.json"
            file_path = symbol_dir / filename
            
            summary_data = {
                "schema_version": "e1.1",
                "symbol": symbol,
                "hour_utc": hour.isoformat() + "Z",
                "generated_at_utc": datetime.now(timezone.utc).isoformat() + "Z",
                "window_utc": {
                    "hour_start": hour.isoformat() + "Z",
                    "hour_end": (hour + timedelta(hours=1)).isoformat() + "Z"
                },
                "bins_max_bps": 50,
                "percentiles_used": [0.5, 0.9],
                "counts": {"orders": 10, "quotes": 20, "fills": 5},
                "hit_rate_by_bin": {"0": {"count": 10, "fills": 2}, "5": {"count": 10, "fills": 3}},
                "queue_wait_cdf_ms": [{"p": 0.5, "v": 150.0}, {"p": 0.9, "v": 250.0}],
                "metadata": {"git_sha": "test", "cfg_hash": "test"}
            }
            
            with open(file_path, 'w') as f:
                json.dump(summary_data, f)
        
        # Run CLI without explicit timestamps (should use defaults)
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--out", str(out_dir),
            "--min-files", "10",
            "--min-total-count", "100"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        
        # Should succeed (will find files in the default 24h window)
        assert result.returncode == 0, f"CLI with defaults should succeed, got: {result.stderr}"
        
        # Should create output
        live_dist_path = out_dir / "live_distributions.json"
        assert live_dist_path.exists()

    def test_cli_preflight_only_mode(self, tmp_path):
        """Test CLI in preflight-only mode."""
        symbol = "PREFLIGHT"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        
        # Create insufficient files (below threshold)
        self.create_test_summary_files(symbol_dir, symbol, count=2)
        
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T13:00:00Z",
            "--preflight-only",
            "--min-files", "5",  # Above what we have
            "--min-total-count", "200"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        
        # Should fail preflight (exit code 1)
        assert result.returncode == 1, "Preflight should fail with insufficient data"
        assert "Not ready for E2" in result.stdout
        assert "need 3 more valid files" in result.stdout

    def test_cli_deterministic_output_same_seed(self, tmp_path):
        """Test that CLI produces deterministic output with same seed."""
        symbol = "DETERMIN"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir1 = tmp_path / "output1"
        out_dir2 = tmp_path / "output2"
        
        # Create test files
        self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        # Common CLI args
        base_cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T13:00:00Z",
            "--seed", "12345",  # Same seed
            "--round-dp", "6",
            "--min-files", "3",
            "--min-total-count", "30"
        ]
        
        # Run 1
        cmd1 = base_cmd + ["--out", str(out_dir1)]
        result1 = subprocess.run(cmd1, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result1.returncode == 0
        
        # Run 2
        cmd2 = base_cmd + ["--out", str(out_dir2)]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result2.returncode == 0
        
        # Compare output files
        live_path1 = out_dir1 / "live_distributions.json"
        live_path2 = out_dir2 / "live_distributions.json"
        
        assert live_path1.exists() and live_path2.exists()
        
        with open(live_path1, 'r') as f:
            content1 = f.read()
        with open(live_path2, 'r') as f:
            content2 = f.read()
        
        assert content1 == content2, "Same seed should produce identical output"

    def test_cli_custom_parameters(self, tmp_path):
        """Test CLI with custom parameters."""
        symbol = "CUSTOM"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create test files
        self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T13:00:00Z",
            "--out", str(out_dir),
            "--bins-max-bps", "30",  # Custom max bins
            "--percentiles", "0.1,0.3,0.7,0.95",  # Custom percentiles
            "--round-dp", "3",  # Custom precision
            "--report-title", "Custom Test Report",
            "--min-files", "3",
            "--min-total-count", "30"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0
        
        # Check custom parameters were applied
        live_path = out_dir / "live_distributions.json"
        with open(live_path, 'r') as f:
            live_data = json.load(f)
        
        # Should have bins up to 30
        assert "30" in live_data["hit_rate_by_bin"]
        
        # Should have custom percentiles
        cdf = live_data["queue_wait_cdf_ms"]
        cdf_percentiles = sorted([entry["p"] for entry in cdf])
        expected_percentiles = [0.1, 0.3, 0.7, 0.95]
        assert cdf_percentiles == expected_percentiles
        
        # Check report has custom title
        report_path = out_dir / "REPORT_core.md"
        with open(report_path, 'r') as f:
            report_content = f.read()
        
        assert "Custom Test Report" in report_content

    def test_cli_insufficient_data_fails(self, tmp_path):
        """Test that CLI fails gracefully with insufficient data."""
        symbol = "INSUFFICIENT"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        
        # Create only 1 file (below threshold)
        self.create_test_summary_files(symbol_dir, symbol, count=1)
        
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T13:00:00Z",
            "--out", str(out_dir),
            "--min-files", "18",  # Default threshold
            "--min-total-count", "100"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        
        # Should fail gracefully
        assert result.returncode == 1, "Should fail with insufficient data"
        assert "Preflight failed" in result.stdout
        
        # Should not create output files
        live_path = out_dir / "live_distributions.json"
        assert not live_path.exists(), "Should not create output with failed preflight"

    def test_cli_invalid_arguments(self):
        """Test CLI with invalid arguments."""
        # Test invalid percentiles
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", "TEST",
            "--percentiles", "invalid,0.5"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 1
        assert "Error parsing percentiles" in result.stdout
        
        # Test invalid timestamps
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", "TEST",
            "--from-utc", "invalid-time",
            "--to-utc", "2025-01-15T10:00:00Z"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 1
        assert "Error parsing timestamps" in result.stdout

    def test_report_core_has_weights_and_units(self, tmp_path):
        """Test that report_core.json contains weights and REPORT_core.md contains Units."""
        symbol = "WEIGHTSTEST"
        summaries_dir = tmp_path / "summaries"
        symbol_dir = summaries_dir / symbol
        symbol_dir.mkdir(parents=True)
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        
        # Create test files
        self.create_test_summary_files(symbol_dir, symbol, count=20)
        
        # Create SIM fixture for weights testing
        sim_fixture = {
            "queue_wait_cdf_ms": [
                {"p": 0.25, "v": 95.0},
                {"p": 0.5, "v": 145.0},
                {"p": 0.75, "v": 195.0},
                {"p": 0.9, "v": 245.0}
            ],
            "hit_rate_by_bin": {
                "0": {"count": 50, "fills": 12},
                "5": {"count": 45, "fills": 11},
                "10": {"count": 48, "fills": 10}
            },
            "sim_hit": 0.235,
            "sim_maker": 0.188
        }
        
        sim_path = out_dir / "sim_fixture.json"
        with open(sim_path, 'w') as f:
            json.dump(sim_fixture, f, indent=2, sort_keys=True)
        
        # Run CLI
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--symbol", symbol,
            "--summaries-dir", str(summaries_dir),
            "--from-utc", "2025-01-15T10:00:00Z",
            "--to-utc", "2025-01-15T13:00:00Z",
            "--out", str(out_dir),
            "--min-files", "3",
            "--min-total-count", "30"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, f"CLI should succeed, got: {result.stderr}"
        
        # Check report_core.json contains weights
        report_core_path = out_dir / "report_core.json"
        assert report_core_path.exists()
        
        with open(report_core_path, 'r') as f:
            report_data = json.load(f)
        
        # E2 Part 1 Polish: Should contain weights
        assert "weights" in report_data, "report_core.json should contain weights"
        
        weights = report_data["weights"]
        expected_keys = {"KS_queue", "KS_bins", "L_hit", "L_maker", "L_reg"}
        assert set(weights.keys()) == expected_keys, f"Weights should have keys: {expected_keys}"
        
        # All weights should be numbers
        for key, value in weights.items():
            assert isinstance(value, (int, float)), f"Weight {key} should be numeric, got {type(value)}"
        
        # Check REPORT_core.md contains Units section
        report_md_path = out_dir / "REPORT_core.md"
        assert report_md_path.exists()
        
        with open(report_md_path, 'r') as f:
            report_content = f.read()
        
        # E2 Part 1 Polish: Should contain Units section
        assert "## Units" in report_content, "REPORT_core.md should contain Units section"
        assert "queue-wait in ms; hit rates shown as %; bins in bps" in report_content
        
        # Should also contain KS normalization note (since SIM is present)
        assert "KS distances are normalized to [0,1]" in report_content
        assert "CDF KS uses live IQR" in report_content

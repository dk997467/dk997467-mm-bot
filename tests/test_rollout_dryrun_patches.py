"""
Tests for F1 rollout CLI dry-run functionality.
"""

import json
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime, timezone

import pytest


class TestRolloutDryRun:
    """Test F1 rollout CLI dry-run functionality."""

    def create_mock_d2_report(self, tmp_path: Path, **overrides) -> Path:
        """Create mock D2 walk-forward report file."""
        base_report = {
            "metadata": {
                "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "symbol": "BTCUSDT"
            },
            "champion": {
                "parameters": {
                    "k_vola_spread": 1.5,
                    "skew_coeff": 0.1,
                    "levels_per_side": 3,
                    "level_spacing_coeff": 1.2,
                    "min_time_in_book_ms": 1000,
                    "replace_threshold_bps": 2.0,
                    "imbalance_cutoff": 0.8,
                    "excluded_param": 999.0  # Should not appear in patches
                },
                "aggregates": {
                    "hit_rate_mean": 0.25,
                    "maker_share_mean": 0.95,
                    "net_pnl_mean_usd": 50.0,
                    "cvar95_mean_usd": -5.0,
                    "win_ratio": 0.70
                }
            },
            "baseline_drift_pct": {
                "k_vola_spread": 5.0,
                "skew_coeff": -3.0,
                "levels_per_side": 0.0
            }
        }
        
        # Apply overrides
        for key, value in overrides.items():
            keys = key.split('.')
            target = base_report
            for k in keys[:-1]:
                target = target[k]
            target[keys[-1]] = value
        
        report_path = tmp_path / "d2_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(base_report, f, indent=2)
        
        return report_path

    def create_mock_e2_report(self, tmp_path: Path, sim_live_divergence=0.1) -> Path:
        """Create mock E2 calibration report file."""
        report = {
            "metadata": {
                "symbol": "BTCUSDT",
                "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            },
            "go_no_go": {
                "ks_queue_after": 0.15,
                "ks_bins_after": 0.05,
                "w4_effective": 0.0,
                "sim_live_divergence": sim_live_divergence,
                "loss_before": 0.5,
                "loss_after": 0.4,
                "loss_regressed": False
            }
        }
        
        report_path = tmp_path / "e2_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        return report_path

    def create_mock_thresholds(self, tmp_path: Path, **overrides) -> Path:
        """Create mock thresholds YAML file."""
        base_thresholds = {
            "min_hit_rate": 0.01,
            "min_maker_share": 0.90,
            "min_net_pnl_usd": 0.0,
            "max_cvar95_loss_usd": 10.0,
            "min_splits_win_ratio": 0.60,
            "max_param_drift_pct": 50.0,
            "max_sim_live_divergence": 0.15,
            "max_report_age_hours": 72
        }
        
        base_thresholds.update(overrides)
        
        thresholds_path = tmp_path / "thresholds.yaml"
        # Write as JSON since YAML might not be available
        with open(thresholds_path, 'w', encoding='utf-8') as f:
            json.dump(base_thresholds, f, indent=2)
        
        return thresholds_path

    def run_rollout_cli(self, *args) -> subprocess.CompletedProcess:
        """Run rollout CLI with given arguments."""
        cmd = ["python", "-m", "src.deploy.rollout"] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, cwd=".")

    def test_pass_scenario_exit_code_0(self, tmp_path):
        """Test successful gate evaluation returns exit code 0."""
        d2_report = self.create_mock_d2_report(tmp_path)
        e2_report = self.create_mock_e2_report(tmp_path, sim_live_divergence=0.1)
        
        result = self.run_rollout_cli(
            "--report", str(d2_report),
            "--calibration-report", str(e2_report),
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 0
        assert "GATE RESULT: PASS" in result.stdout
        assert "symbol: TESTBTC" in result.stdout

    def test_fail_scenario_exit_code_2(self, tmp_path):
        """Test failed gate evaluation returns exit code 2."""
        # Create report with low hit rate to trigger failure
        d2_report = self.create_mock_d2_report(tmp_path, **{"champion.aggregates.hit_rate_mean": 0.005})
        
        result = self.run_rollout_cli(
            "--report", str(d2_report),
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 2
        assert "GATE RESULT: FAIL" in result.stdout
        assert "hit rate too low" in result.stdout.lower()

    def test_patches_are_valid_json(self, tmp_path):
        """Test that both full and canary patches are valid JSON."""
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", str(d2_report),
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 0
        
        # Extract JSON patches from output
        output_lines = result.stdout.split('\n')
        
        # Find Full patch
        full_start = None
        full_end = None
        for i, line in enumerate(output_lines):
            if "Full patch (JSON):" in line:
                full_start = i + 1
            elif full_start is not None and line.strip() == "" and i > full_start:
                full_end = i
                break
        
        assert full_start is not None, "Full patch section not found"
        full_json_text = '\n'.join(output_lines[full_start:full_end])
        
        # Validate Full patch JSON
        full_patch = json.loads(full_json_text)
        assert isinstance(full_patch, dict)
        
        # Find Canary patch
        canary_start = None
        for i, line in enumerate(output_lines):
            if "Canary patch (JSON):" in line:
                canary_start = i + 1
                break
        
        assert canary_start is not None, "Canary patch section not found"
        canary_json_text = '\n'.join(output_lines[canary_start:])
        
        # Validate Canary patch JSON
        canary_patch = json.loads(canary_json_text)
        assert isinstance(canary_patch, dict)

    def test_patches_contain_expected_params(self, tmp_path):
        """Test that patches contain expected whitelisted parameters."""
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", str(d2_report),
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 0
        
        # Extract patches (simplified extraction for testing)
        output = result.stdout
        
        # Verify Full patch contains whitelisted params
        assert '"k_vola_spread": 1.5' in output
        assert '"levels_per_side": 3' in output
        assert '"level_spacing_coeff": 1.2' in output
        
        # Verify excluded param is not in patches
        assert "excluded_param" not in output
        
        # Verify Canary patch has conservative modifications
        assert '"levels_per_side": 1' in output  # Should be reduced (3 * 0.5 = 1.5 -> 1)

    def test_high_divergence_causes_failure(self, tmp_path):
        """Test that high E2 divergence causes gate failure."""
        d2_report = self.create_mock_d2_report(tmp_path)
        e2_report = self.create_mock_e2_report(tmp_path, sim_live_divergence=0.25)  # > 0.15
        
        result = self.run_rollout_cli(
            "--report", str(d2_report),
            "--calibration-report", str(e2_report),
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 2
        assert "GATE RESULT: FAIL" in result.stdout
        assert "divergence too high" in result.stdout.lower()
        assert "sim_live_divergence: 0.25" in result.stdout

    def test_without_calibration_report(self, tmp_path):
        """Test operation without E2 calibration report."""
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", str(d2_report),
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 0
        assert "GATE RESULT: PASS" in result.stdout
        assert "sim_live_divergence: n/a" in result.stdout

    def test_custom_thresholds(self, tmp_path):
        """Test using custom thresholds file."""
        d2_report = self.create_mock_d2_report(tmp_path)
        # Create strict thresholds that will cause failure
        thresholds = self.create_mock_thresholds(tmp_path, min_hit_rate=0.30)  # Higher than 0.25 in report
        
        result = self.run_rollout_cli(
            "--report", str(d2_report),
            "--thresholds", str(thresholds),
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 2
        assert "GATE RESULT: FAIL" in result.stdout
        assert "hit rate too low" in result.stdout.lower()

    def test_output_format_and_sections(self, tmp_path):
        """Test that output contains all expected sections."""
        d2_report = self.create_mock_d2_report(tmp_path)
        e2_report = self.create_mock_e2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", str(d2_report),
            "--calibration-report", str(e2_report),
            "--symbol", "TESTBTC",
            "--round-dp", "3"
        )
        
        assert result.returncode == 0
        output = result.stdout
        
        # Check required sections
        assert "GATE RESULT: PASS" in output
        assert "symbol: TESTBTC" in output
        assert "timestamp:" in output
        
        # Check metrics section
        assert "Metrics:" in output
        assert "age_hours:" in output
        assert "win_ratio:" in output
        assert "hit_rate:" in output
        assert "maker_share:" in output
        assert "pnl_usd:" in output
        assert "cvar95_usd:" in output
        assert "drift_max_pct:" in output
        assert "sim_live_divergence:" in output
        
        # Check thresholds section
        assert "thresholds:" in output
        
        # Check reasons section
        assert "Reasons:" in output
        
        # Check patch sections
        assert "Full patch (JSON):" in output
        assert "Canary patch (JSON):" in output

    def test_missing_file_exit_code_1(self, tmp_path):
        """Test that missing files cause exit code 1."""
        result = self.run_rollout_cli(
            "--report", "/nonexistent/file.json",
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 1
        assert "[ERROR]" in result.stderr

    def test_invalid_json_exit_code_1(self, tmp_path):
        """Test that invalid JSON causes exit code 1."""
        bad_json_path = tmp_path / "bad.json"
        with open(bad_json_path, 'w') as f:
            f.write("{ invalid json }")
        
        result = self.run_rollout_cli(
            "--report", str(bad_json_path),
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 1
        assert "[ERROR]" in result.stderr

    def test_round_dp_parameter(self, tmp_path):
        """Test that round-dp parameter affects output formatting."""
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", str(d2_report),
            "--symbol", "TESTBTC",
            "--round-dp", "2"
        )
        
        assert result.returncode == 0
        
        # Verify rounding to 2 decimal places in output
        # Note: This is a simple check - in practice might need more sophisticated parsing
        output = result.stdout
        assert "hit_rate: 0.25" in output  # Should be rounded to 2 decimal places

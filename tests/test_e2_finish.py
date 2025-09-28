"""
Tests for E2 finish checklist validation.
"""

import json
import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch


class TestE2FinishValidation:
    """Test E2 finish checklist validation functionality."""
    
    def create_valid_report_json(self, round_dp: int = 6) -> dict:
        """Create a valid report.json structure for testing."""
        return {
            "metadata": {
                "symbol": "TESTBTC",
                "seed": 42,
                "round_dp": round_dp
            },
            "live_distributions": {
                "live_hit": 0.25,
                "live_maker": 0.22
            },
            "loss_after": {
                "KS_queue": 0.234567,
                "KS_bins": 0.156789,
                "L_hit": 0.045123,
                "L_maker": 0.012345,
                "TotalLoss": 0.389456
            },
            "go_no_go": {
                "ks_queue_after": round(0.234567, round_dp),
                "ks_bins_after": round(0.156789, round_dp),
                "w4_effective": round(0.5, round_dp),
                "sim_live_divergence": round(0.195678, round_dp),
                "loss_before": round(0.425123, round_dp),
                "loss_after": round(0.389456, round_dp),
                "loss_regressed": False
            }
        }
    
    def test_go_no_go_keys_rounded(self, tmp_path):
        """Test go_no_go validation with proper rounding."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        
        # Test with valid report
        valid_report = self.create_valid_report_json(round_dp=6)
        report_path = out_dir / "report.json"
        
        with open(report_path, 'w') as f:
            json.dump(valid_report, f, indent=2)
        
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--finish-check-only",
            "--out", str(out_dir),
            "--symbol", "TESTBTC"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, f"Valid report should pass, got: {result.stderr}"
        assert "E2 finish: OK" in result.stdout
        
        # Test with invalid rounding (not rounded to round_dp)
        invalid_report = self.create_valid_report_json(round_dp=6)
        invalid_report["go_no_go"]["ks_queue_after"] = 0.2345678901234  # Too many decimal places
        
        with open(report_path, 'w') as f:
            json.dump(invalid_report, f, indent=2)
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 2, "Invalid rounding should fail"
        output = result.stdout + result.stderr
        assert "ks_queue_after" in output
        
        # Test with missing key
        incomplete_report = self.create_valid_report_json(round_dp=6)
        del incomplete_report["go_no_go"]["sim_live_divergence"]
        
        with open(report_path, 'w') as f:
            json.dump(incomplete_report, f, indent=2)
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 2, "Missing key should fail"
        output = result.stdout + result.stderr
        assert "sim_live_divergence" in output

    def test_effective_w4_and_maker_zero(self, tmp_path):
        """Test w4_effective and L_maker validation when live_maker is None."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        report_path = out_dir / "report.json"
        
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--finish-check-only",
            "--out", str(out_dir),
            "--symbol", "TESTBTC"
        ]
        
        # Test valid case: live_maker=None, w4_effective=0.0, L_maker=0.0
        valid_report = self.create_valid_report_json(round_dp=6)
        valid_report["live_distributions"]["live_maker"] = None
        valid_report["go_no_go"]["w4_effective"] = 0.0
        valid_report["loss_after"]["L_maker"] = 0.0
        
        with open(report_path, 'w') as f:
            json.dump(valid_report, f, indent=2)
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, "Valid None live_maker case should pass"
        assert "E2 finish: OK" in result.stdout
        
        # Test invalid case: live_maker=None but w4_effective != 0.0
        invalid_report = self.create_valid_report_json(round_dp=6)
        invalid_report["live_distributions"]["live_maker"] = None
        invalid_report["go_no_go"]["w4_effective"] = 0.1  # Should be 0.0
        invalid_report["loss_after"]["L_maker"] = 0.0
        
        with open(report_path, 'w') as f:
            json.dump(invalid_report, f, indent=2)
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 2, "Invalid w4_effective should fail"
        output = result.stdout + result.stderr
        assert "w4_effective should be 0.0" in output
        
        # Test invalid case: live_maker=None but L_maker != 0.0
        invalid_report = self.create_valid_report_json(round_dp=6)
        invalid_report["live_distributions"]["live_maker"] = None
        invalid_report["go_no_go"]["w4_effective"] = 0.0
        invalid_report["loss_after"]["L_maker"] = 0.1  # Should be 0.0
        
        with open(report_path, 'w') as f:
            json.dump(invalid_report, f, indent=2)
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 2, "Invalid L_maker should fail"
        output = result.stdout + result.stderr
        assert "L_maker should be 0.0" in output

    def test_calibration_determinism_same_seed(self, tmp_path):
        """Test determinism check between calibration.json and calibration.json.ref."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        
        # Create identical calibration files
        calibration_data = {
            "latency_ms_mean": 100.0,
            "latency_ms_std": 10.0,
            "amend_latency_ms": 50.0,
            "cancel_latency_ms": 30.0,
            "toxic_sweep_prob": 0.05,
            "extra_slippage_bps": 2.5
        }
        
        calibration_path = out_dir / "calibration.json"
        calibration_ref_path = out_dir / "calibration.json.ref"
        
        # Write identical content to both files
        with open(calibration_path, 'w') as f:
            json.dump(calibration_data, f, sort_keys=True, indent=2)
        with open(calibration_ref_path, 'w') as f:
            json.dump(calibration_data, f, sort_keys=True, indent=2)
        
        # Create valid report.json
        valid_report = self.create_valid_report_json(round_dp=6)
        report_path = out_dir / "report.json"
        
        with open(report_path, 'w') as f:
            json.dump(valid_report, f, indent=2)
        
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--finish-check-only",
            "--out", str(out_dir),
            "--symbol", "TESTBTC"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, "Identical files should pass"
        assert "determinism: MATCH" in result.stdout
        assert "E2 finish: OK" in result.stdout
        
        # Test with different content
        different_data = calibration_data.copy()
        different_data["latency_ms_mean"] = 110.0  # Different value
        
        with open(calibration_ref_path, 'w') as f:
            json.dump(different_data, f, sort_keys=True, indent=2)
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 0, "Determinism check should not affect exit code"
        assert "determinism: DIFF" in result.stdout
        assert "E2 finish: OK" in result.stdout

    def test_missing_report_json(self, tmp_path):
        """Test handling of missing report.json file."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--finish-check-only",
            "--out", str(out_dir),
            "--symbol", "TESTBTC"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 2, "Missing report.json should fail"
        # Error message could be in stdout or stderr
        output = result.stdout + result.stderr
        assert "report.json not found" in output

    def test_missing_go_no_go_block(self, tmp_path):
        """Test handling of missing go_no_go block."""
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        report_path = out_dir / "report.json"
        
        # Create report without go_no_go block
        incomplete_report = {
            "metadata": {"symbol": "TESTBTC"},
            "live_distributions": {"live_hit": 0.25}
        }
        
        with open(report_path, 'w') as f:
            json.dump(incomplete_report, f, indent=2)
        
        cmd = [
            "python", "-m", "src.research.calibrate",
            "--finish-check-only",
            "--out", str(out_dir),
            "--symbol", "TESTBTC"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="C:/Users/dimak/mm-bot")
        assert result.returncode == 2, "Missing go_no_go block should fail"
        output = result.stdout + result.stderr
        assert "Missing go_no_go block" in output

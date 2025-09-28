"""
Tests for F2 rollout CLI apply functionality.
"""

import pytest
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.deploy.rollout import main


class TestRolloutCLIApply:
    """Test F2 rollout CLI with --apply flag."""

    def create_mock_d2_report(self, tmp_path: Path) -> str:
        """Create mock D2 report file."""
        report = {
            "metadata": {
                "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "symbol": "TESTBTC"
            },
            "champion": {
                "parameters": {
                    "k_vola_spread": 1.5,
                    "levels_per_side": 4,
                    "level_spacing_coeff": 1.2,
                    "min_time_in_book_ms": 1000
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
                "levels_per_side": 0.0
            }
        }
        
        report_path = tmp_path / "d2_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        return str(report_path)

    def create_mock_e2_report(self, tmp_path: Path) -> str:
        """Create mock E2 report file."""
        report = {
            "metadata": {
                "symbol": "TESTBTC",
                "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            },
            "go_no_go": {
                "ks_queue_after": 0.10,
                "ks_bins_after": 0.05,
                "w4_effective": 0.0,
                "sim_live_divergence": 0.08,
                "loss_before": 0.5,
                "loss_after": 0.4,
                "loss_regressed": False
            }
        }
        
        report_path = tmp_path / "e2_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        return str(report_path)

    def run_rollout_cli(self, *args) -> subprocess.CompletedProcess:
        """Run rollout CLI with given arguments."""
        cmd = ["python", "-m", "src.deploy.rollout"] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, cwd=".")

    def test_f1_dry_run_behavior_unchanged(self, tmp_path):
        """Test that F1 dry-run behavior is unchanged."""
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", d2_report,
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 0
        assert "GATE RESULT: PASS" in result.stdout
        assert "Full patch (JSON):" in result.stdout
        assert "Canary patch (JSON):" in result.stdout
        assert "[F2]" not in result.stdout  # No F2 messages in dry-run mode

    def test_apply_missing_admin_url(self, tmp_path):
        """Test that --apply requires --admin-url."""
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", d2_report,
            "--symbol", "TESTBTC",
            "--apply"
        )
        
        assert result.returncode == 1
        assert "admin-url is required when using --apply" in result.stderr

    def test_apply_missing_metrics_url(self, tmp_path):
        """Test that --apply requires --metrics-url."""
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", d2_report,
            "--symbol", "TESTBTC",
            "--apply",
            "--admin-url", "http://localhost:8080"
        )
        
        assert result.returncode == 1
        assert "metrics-url is required when using --apply" in result.stderr

    @patch('src.deploy.rollout._http_get_json')
    @patch('src.deploy.rollout._http_post_json')
    @patch('src.deploy.rollout.monitor_metrics')
    @patch('src.deploy.rollout.write_audit_log')
    def test_successful_canary_promote(self, mock_audit, mock_monitor, mock_post, mock_get, tmp_path):
        """Test successful canary→promote flow."""
        # Setup mocks
        mock_get.side_effect = [
            {"cfg_hash": "baseline_hash", "timestamp": 1234567890},  # pre-snapshot
            {"cfg_hash": "full_hash", "timestamp": 1234567920}       # post-snapshot
        ]
        mock_post.side_effect = [
            {"ok": True, "applied": True, "cfg_hash_after": "canary_hash"},  # canary apply
            {"ok": True, "applied": True, "cfg_hash_after": "full_hash"}     # full apply
        ]
        mock_monitor.return_value = (True, [], {"polls_completed": 5, "duration_minutes": 0.1})
        mock_audit.return_value = str(tmp_path / "audit.json")
        
        # Create reports
        d2_report = self.create_mock_d2_report(tmp_path)
        e2_report = self.create_mock_e2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", d2_report,
            "--calibration-report", e2_report,
            "--symbol", "TESTBTC",
            "--apply",
            "--admin-url", "http://localhost:8080",
            "--metrics-url", "http://localhost:8080/metrics",
            "--canary-minutes", "0.1"
        )
        
        assert result.returncode == 0
        assert "[F2] Starting deployment for TESTBTC" in result.stdout
        assert "[F2] Canary monitoring PASSED" in result.stdout
        assert "[F2] Outcome: PROMOTED" in result.stdout
        
        # Verify API calls
        assert mock_get.call_count == 2  # pre and post snapshots
        assert mock_post.call_count == 2  # canary and full patches
        mock_monitor.assert_called_once()
        mock_audit.assert_called_once()

    @patch('src.deploy.rollout._http_get_json')
    @patch('src.deploy.rollout._http_post_json')
    @patch('src.deploy.rollout.monitor_metrics')
    @patch('src.deploy.rollout.write_audit_log')
    def test_canary_degradation_rollback(self, mock_audit, mock_monitor, mock_post, mock_get, tmp_path):
        """Test canary degradation→rollback flow."""
        # Setup mocks for degradation scenario
        mock_get.side_effect = [
            {"cfg_hash": "baseline_hash", "timestamp": 1234567890},  # pre-snapshot
            {"cfg_hash": "baseline_hash", "timestamp": 1234567920}   # post-rollback snapshot
        ]
        mock_post.side_effect = [
            {"ok": True, "applied": True, "cfg_hash_after": "canary_hash"},  # canary apply
            {"ok": True, "rolled_back": True, "cfg_hash_after": "baseline_hash"}  # rollback
        ]
        # Monitor detects degradation
        mock_monitor.return_value = (False, ["Cancel rate too high: 95.0 > 90.0"], {
            "polls_completed": 3,
            "duration_minutes": 0.05,
            "degraded_rules": ["high_cancel_rate"]
        })
        mock_audit.return_value = str(tmp_path / "audit.json")
        
        # Create reports
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", d2_report,
            "--symbol", "TESTBTC",
            "--apply",
            "--admin-url", "http://localhost:8080",
            "--metrics-url", "http://localhost:8080/metrics",
            "--canary-minutes", "0.1"
        )
        
        assert result.returncode == 2
        assert "[F2] DEGRADATION DETECTED" in result.stdout
        assert "[F2] ROLLING BACK configuration" in result.stdout
        assert "[F2] Outcome: ROLLED_BACK" in result.stdout
        assert "Cancel rate too high" in result.stdout
        
        # Verify rollback was called
        rollback_call = mock_post.call_args_list[1]
        assert "/admin/rollback" in rollback_call[0][0]

    @patch('src.deploy.rollout._http_get_json')
    def test_unreachable_admin_url(self, mock_get, tmp_path):
        """Test error handling for unreachable admin URL."""
        mock_get.side_effect = ConnectionError("Failed to connect to http://unreachable:8080/admin/snapshot")
        
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", d2_report,
            "--symbol", "TESTBTC",
            "--apply",
            "--admin-url", "http://unreachable:8080",
            "--metrics-url", "http://unreachable:8080/metrics",
            "--canary-minutes", "0.1"
        )
        
        assert result.returncode == 1
        assert "[F2] Network/API error:" in result.stdout
        assert "[F2] Outcome: ERROR" in result.stdout

    @patch('src.deploy.rollout._http_get_json')
    @patch('src.deploy.rollout._http_post_json')
    @patch('src.deploy.rollout.monitor_metrics')
    def test_gate_failure_blocks_apply(self, mock_monitor, mock_post, mock_get, tmp_path):
        """Test that gate failure prevents F2 deployment."""
        # Create report with failing metrics (low hit rate)
        report = {
            "metadata": {
                "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "symbol": "TESTBTC"
            },
            "champion": {
                "parameters": {"k_vola_spread": 1.5},
                "aggregates": {
                    "hit_rate_mean": 0.005,  # Below 0.01 threshold
                    "maker_share_mean": 0.95,
                    "net_pnl_mean_usd": 50.0,
                    "cvar95_mean_usd": -5.0,
                    "win_ratio": 0.70
                }
            }
        }
        
        report_path = tmp_path / "failing_d2_report.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        result = self.run_rollout_cli(
            "--report", str(report_path),
            "--symbol", "TESTBTC",
            "--apply",
            "--admin-url", "http://localhost:8080",
            "--metrics-url", "http://localhost:8080/metrics"
        )
        
        assert result.returncode == 2
        assert "GATE RESULT: FAIL" in result.stdout
        assert "[F2] Gate evaluation FAILED - aborting deployment" in result.stdout
        
        # Verify no HTTP calls were made (deployment was blocked)
        mock_get.assert_not_called()
        mock_post.assert_not_called()
        mock_monitor.assert_not_called()

    def test_canary_shrink_parameter(self, tmp_path):
        """Test custom canary shrink factor."""
        d2_report = self.create_mock_d2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", d2_report,
            "--symbol", "TESTBTC",
            "--canary-shrink", "0.25"  # Custom shrink factor
        )
        
        assert result.returncode == 0
        
        # Check that canary patch uses custom shrink factor
        # levels_per_side should be reduced: 4 * 0.25 = 1
        assert '"levels_per_side": 1' in result.stdout

    @patch('src.deploy.rollout.write_audit_log')
    def test_audit_log_content(self, mock_audit, tmp_path):
        """Test audit log contains required fields."""
        mock_audit.return_value = str(tmp_path / "audit.json")
        
        d2_report = self.create_mock_d2_report(tmp_path)
        e2_report = self.create_mock_e2_report(tmp_path)
        
        # Run dry-run to capture audit call (if any)
        result = self.run_rollout_cli(
            "--report", d2_report,
            "--calibration-report", e2_report,
            "--symbol", "TESTBTC"
        )
        
        assert result.returncode == 0
        
        # In dry-run mode, audit should not be called
        mock_audit.assert_not_called()

    @patch('src.deploy.rollout._http_get_json')
    @patch('src.deploy.rollout._http_post_json')
    @patch('src.deploy.rollout.monitor_metrics')
    @patch('src.deploy.rollout.write_audit_log')
    def test_audit_log_structure_with_apply(self, mock_audit, mock_monitor, mock_post, mock_get, tmp_path):
        """Test audit log structure when using --apply."""
        # Setup successful promote scenario
        mock_get.side_effect = [
            {"cfg_hash": "baseline_hash"},
            {"cfg_hash": "full_hash"}
        ]
        mock_post.side_effect = [
            {"ok": True, "cfg_hash_after": "canary_hash"},
            {"ok": True, "cfg_hash_after": "full_hash"}
        ]
        mock_monitor.return_value = (True, [], {"polls_completed": 5})
        
        # Capture audit data
        audit_data = None
        def capture_audit(symbol, data):
            nonlocal audit_data
            audit_data = data
            return str(tmp_path / "audit.json")
        
        mock_audit.side_effect = capture_audit
        
        d2_report = self.create_mock_d2_report(tmp_path)
        e2_report = self.create_mock_e2_report(tmp_path)
        
        result = self.run_rollout_cli(
            "--report", d2_report,
            "--calibration-report", e2_report,
            "--symbol", "TESTBTC",
            "--apply",
            "--admin-url", "http://localhost:8080",
            "--metrics-url", "http://localhost:8080/metrics",
            "--canary-minutes", "0.1"
        )
        
        assert result.returncode == 0
        assert audit_data is not None
        
        # Verify audit log structure
        required_fields = [
            "now_utc", "symbol", "report_paths", "thresholds",
            "patches", "canary_params", "monitor_stats", 
            "snapshot", "outcome"
        ]
        
        for field in required_fields:
            assert field in audit_data, f"Missing audit field: {field}"
        
        assert audit_data["symbol"] == "TESTBTC"
        assert audit_data["outcome"] == "promoted"
        assert "canary" in audit_data["patches"]
        assert "full" in audit_data["patches"]
        assert "before" in audit_data["snapshot"]
        assert "after" in audit_data["snapshot"]

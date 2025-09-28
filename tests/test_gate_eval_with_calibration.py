"""
Tests for F1 deployment gate evaluation with D2 + E2 integration.
"""

import pytest
from datetime import datetime, timezone, timedelta
from src.deploy.gate import evaluate, build_cfg_patch, make_canary_patch
from src.deploy.thresholds import GateThresholds


class TestGateEvaluation:
    """Test gate evaluation logic with various scenarios."""

    def create_mock_wf_report(self, **overrides):
        """Create mock D2 walk-forward report with default values."""
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
                    "imbalance_cutoff": 0.8
                },
                "aggregates": {
                    "hit_rate_mean": 0.25,
                    "maker_share_mean": 0.95,
                    "net_pnl_mean_usd": 50.0,
                    "cvar95_mean_usd": -5.0,  # Negative for losses
                    "win_ratio": 0.70
                }
            },
            "baseline_drift_pct": {
                "k_vola_spread": 5.0,
                "skew_coeff": -3.0,
                "levels_per_side": 0.0,
                "non_whitelisted_param": 100.0  # Should be ignored
            }
        }
        
        # Apply overrides
        for key, value in overrides.items():
            keys = key.split('.')
            target = base_report
            for k in keys[:-1]:
                target = target[k]
            target[keys[-1]] = value
            
        return base_report

    def create_mock_calib_report(self, sim_live_divergence=0.1):
        """Create mock E2 calibration report."""
        return {
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

    def test_all_gates_pass(self):
        """Test scenario where all gates pass."""
        wf_report = self.create_mock_wf_report()
        calib_report = self.create_mock_calib_report(sim_live_divergence=0.1)
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, calib_report)
        
        assert ok is True
        assert len(reasons) == 0
        assert metrics["hit_rate_mean"] == 0.25
        assert metrics["maker_share_mean"] == 0.95
        assert metrics["net_pnl_mean_usd"] == 50.0
        assert metrics["cvar95_mean_usd"] == -5.0
        assert metrics["win_ratio"] == 0.70
        assert metrics["max_param_drift_pct"] == 5.0  # Max of whitelisted params
        assert metrics["sim_live_divergence"] == 0.1
        assert metrics["report_age_hours"] < 1.0  # Recent report

    def test_high_divergence_fails(self):
        """Test that high sim-live divergence causes failure."""
        wf_report = self.create_mock_wf_report()
        calib_report = self.create_mock_calib_report(sim_live_divergence=0.25)  # > 0.15 threshold
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, calib_report)
        
        assert ok is False
        assert any("divergence too high" in reason.lower() for reason in reasons)
        assert metrics["sim_live_divergence"] == 0.25

    def test_low_hit_rate_fails(self):
        """Test that low hit rate causes failure."""
        wf_report = self.create_mock_wf_report()
        wf_report["champion"]["aggregates"]["hit_rate_mean"] = 0.005  # < 0.01 threshold
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, None)
        
        assert ok is False
        assert any("hit rate too low" in reason.lower() for reason in reasons)
        assert metrics["hit_rate_mean"] == 0.005

    def test_low_maker_share_fails(self):
        """Test that low maker share causes failure."""
        wf_report = self.create_mock_wf_report()
        wf_report["champion"]["aggregates"]["maker_share_mean"] = 0.85  # < 0.90 threshold
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, None)
        
        assert ok is False
        assert any("maker share too low" in reason.lower() for reason in reasons)
        assert metrics["maker_share_mean"] == 0.85

    def test_high_cvar95_fails(self):
        """Test that high CVaR95 loss causes failure."""
        wf_report = self.create_mock_wf_report()
        wf_report["champion"]["aggregates"]["cvar95_mean_usd"] = -15.0  # abs(15) > 10 threshold
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, None)
        
        assert ok is False
        assert any("cvar95 loss too high" in reason.lower() for reason in reasons)
        assert metrics["cvar95_mean_usd"] == -15.0

    def test_low_win_ratio_fails(self):
        """Test that low win ratio causes failure."""
        wf_report = self.create_mock_wf_report()
        wf_report["champion"]["aggregates"]["win_ratio"] = 0.50  # < 0.60 threshold
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, None)
        
        assert ok is False
        assert any("win ratio too low" in reason.lower() for reason in reasons)
        assert metrics["win_ratio"] == 0.50

    def test_high_drift_fails(self):
        """Test that high parameter drift causes failure."""
        wf_report = self.create_mock_wf_report()
        wf_report["baseline_drift_pct"]["k_vola_spread"] = 60.0  # > 50% threshold
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, None)
        
        assert ok is False
        assert any("drift too high" in reason.lower() for reason in reasons)
        assert metrics["max_param_drift_pct"] == 60.0

    def test_old_report_fails(self):
        """Test that old report causes failure."""
        # Create report that's 100 hours old
        old_timestamp = (datetime.now(timezone.utc) - timedelta(hours=100)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        wf_report = self.create_mock_wf_report()
        wf_report["metadata"]["generated_at_utc"] = old_timestamp
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, None)
        
        assert ok is False
        assert any("too old" in reason.lower() for reason in reasons)
        assert metrics["report_age_hours"] > 72  # > threshold

    def test_without_calibration_report(self):
        """Test that evaluation works without E2 calibration report."""
        wf_report = self.create_mock_wf_report()
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, None)
        
        assert ok is True  # Should pass without calibration report
        assert len(reasons) == 0
        assert metrics["sim_live_divergence"] is None

    def test_divergence_clamping(self):
        """Test that divergence values are clamped to [0, 1]."""
        wf_report = self.create_mock_wf_report()
        calib_report = self.create_mock_calib_report(sim_live_divergence=1.5)  # > 1.0
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, calib_report)
        
        assert metrics["sim_live_divergence"] == 1.0  # Clamped to max

    def test_negative_divergence_clamping(self):
        """Test that negative divergence values are clamped to 0."""
        wf_report = self.create_mock_wf_report()
        calib_report = self.create_mock_calib_report(sim_live_divergence=-0.1)  # < 0.0
        thresholds = GateThresholds()
        
        ok, reasons, metrics = evaluate(wf_report, thresholds, None, calib_report)
        
        assert metrics["sim_live_divergence"] == 0.0  # Clamped to min


class TestConfigPatches:
    """Test configuration patch generation."""

    def test_build_cfg_patch_whitelist(self):
        """Test that cfg patch only includes whitelisted parameters."""
        champion_params = {
            "k_vola_spread": 1.5,
            "skew_coeff": 0.1,
            "levels_per_side": 3,
            "level_spacing_coeff": 1.2,
            "min_time_in_book_ms": 1000,
            "replace_threshold_bps": 2.0,
            "imbalance_cutoff": 0.8,
            "non_whitelisted_param": 999.0,  # Should be excluded
            "another_param": "test"  # Should be excluded
        }
        
        patch = build_cfg_patch(champion_params)
        
        # Should only include whitelisted parameters
        expected_keys = {
            "k_vola_spread", "skew_coeff", "levels_per_side",
            "level_spacing_coeff", "min_time_in_book_ms",
            "replace_threshold_bps", "imbalance_cutoff"
        }
        
        assert set(patch.keys()) == expected_keys
        assert patch["k_vola_spread"] == 1.5
        assert patch["levels_per_side"] == 3
        assert "non_whitelisted_param" not in patch
        assert "another_param" not in patch

    def test_make_canary_patch_conservative(self):
        """Test that canary patch applies conservative modifications."""
        full_patch = {
            "k_vola_spread": 1.5,
            "levels_per_side": 4,
            "level_spacing_coeff": 1.0,
            "min_time_in_book_ms": 1000
        }
        
        canary_patch = make_canary_patch(full_patch, shrink=0.5, min_levels=1)
        
        # Levels should be reduced by shrink factor
        assert canary_patch["levels_per_side"] == 2  # 4 * 0.5 = 2
        
        # Spacing should be increased (wider spreads)
        assert canary_patch["level_spacing_coeff"] == 1.1  # 1.0 * 1.1
        
        # Min time should be increased (more conservative)
        assert canary_patch["min_time_in_book_ms"] == 1100  # 1000 * 1.1
        
        # Other params should remain unchanged
        assert canary_patch["k_vola_spread"] == 1.5

    def test_canary_patch_min_levels(self):
        """Test that canary patch respects minimum levels."""
        full_patch = {
            "levels_per_side": 2
        }
        
        canary_patch = make_canary_patch(full_patch, shrink=0.3, min_levels=1)
        
        # Should respect min_levels even if shrink would go below
        assert canary_patch["levels_per_side"] == 1  # max(1, int(2 * 0.3)) = max(1, 0) = 1

    def test_empty_patches(self):
        """Test handling of empty parameter sets."""
        empty_params = {}
        
        patch = build_cfg_patch(empty_params)
        canary_patch = make_canary_patch(patch)
        
        assert patch == {}
        assert canary_patch == {}

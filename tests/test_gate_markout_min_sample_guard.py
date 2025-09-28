"""Test markout min_sample guard in canary gate evaluation."""

import pytest
from unittest.mock import Mock, patch
from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


class TestGateMarkoutMinSampleGuard:
    """Test that markout gate respects min_sample guard."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.thresholds = GateThresholds()
        
        # Base canary report with champion metrics
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        self.canary_report = {
            "symbol": "BTCUSDT",
            "metadata": {
                "created_at_utc": now_utc.isoformat()
            },
            "champion": {
                "aggregates": {
                    "hit_rate_mean": 0.95,
                    "maker_share_mean": 0.92,
                    "net_pnl_mean_usd": 100.0,
                    "cvar95_mean_usd": -5.0,
                    "win_ratio": 0.65
                }
            },
            "canary": {
                "killswitch_fired": False,
                "drift_alert": False,
                "fills_blue": 100,
                "fills_green": 100,
                "rejects_blue": 5,
                "rejects_green": 5,
                "latency_ms_avg_blue": 25.0,
                "latency_ms_avg_green": 25.0,
                "latency_samples_blue": 200,
                "latency_samples_green": 200,
                "latency_ms_p95_blue": 50.0,
                "latency_ms_p95_green": 50.0,
                "latency_ms_p99_blue": 100.0,
                "latency_ms_p99_green": 100.0,
            }
        }
    
    def test_markout_guard_low_samples_200ms(self):
        """Test that markout gate doesn't trigger with low 200ms samples."""
        # Set low samples for 200ms, sufficient for 500ms
        self.canary_report["canary"].update({
            "markout_samples_200_blue": 30,  # Below 50 threshold
            "markout_samples_200_green": 30,
            "markout_samples_500_blue": 100,  # Above 50 threshold
            "markout_samples_500_green": 100,
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": -10.0,  # Green worse by 15 bps
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": -20.0,  # Green worse by 30 bps
        })
        
        with patch('src.deploy.gate.get_canary_gate_thresholds') as mock_get:
            mock_get.return_value = {
                "max_reject_delta": 0.02,
                "max_latency_delta_ms": 50,
                "min_sample_fills": 100,  # Lower threshold to allow evaluation
                "drift_cap_pct": 5.0,
                "tail_min_sample": 200,
                "tail_p95_cap_ms": 50,
                "tail_p99_cap_ms": 100,
                "slo_tail_min_sample": 200,
                "slo_tail_p95_cap_ms": 50,
                "slo_tail_p99_cap_ms": 100,
                "markout_min_sample": 50,
                "markout_cap_bps_200": 0.5,
                "markout_cap_bps_500": 0.5,
            }
            
            ok, reasons, metrics = evaluate(self.canary_report, self.thresholds)
            
            # Should pass due to low samples (guard prevents evaluation)
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' not in canary_reasons
    
    def test_markout_guard_low_samples_500ms(self):
        """Test that markout gate doesn't trigger with low 500ms samples."""
        # Set sufficient samples for 200ms, low for 500ms
        self.canary_report["canary"].update({
            "markout_samples_200_blue": 100,  # Above 50 threshold
            "markout_samples_200_green": 100,
            "markout_samples_500_blue": 25,  # Below 50 threshold
            "markout_samples_500_green": 25,
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": -10.0,  # Green worse by 15 bps
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": -20.0,  # Green worse by 30 bps
        })
        
        with patch('src.deploy.gate.get_canary_gate_thresholds') as mock_get:
            mock_get.return_value = {
                "max_reject_delta": 0.02,
                "max_latency_delta_ms": 50,
                "min_sample_fills": 100,  # Lower threshold to allow evaluation
                "drift_cap_pct": 5.0,
                "tail_min_sample": 200,
                "tail_p95_cap_ms": 50,
                "tail_p99_cap_ms": 100,
                "slo_tail_min_sample": 200,
                "slo_tail_p95_cap_ms": 50,
                "slo_tail_p99_cap_ms": 100,
                "markout_min_sample": 50,
                "markout_cap_bps_200": 0.5,
                "markout_cap_bps_500": 0.5,
            }
            
            ok, reasons, metrics = evaluate(self.canary_report, self.thresholds)
            
            # Should pass due to low samples (guard prevents evaluation)
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' not in canary_reasons
    
    def test_markout_guard_low_samples_both_horizons(self):
        """Test that markout gate doesn't trigger with low samples in both horizons."""
        # Set low samples for both horizons
        self.canary_report["canary"].update({
            "markout_samples_200_blue": 30,  # Below 50 threshold
            "markout_samples_200_green": 30,
            "markout_samples_500_blue": 25,  # Below 50 threshold
            "markout_samples_500_green": 25,
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": -10.0,  # Green worse by 15 bps
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": -20.0,  # Green worse by 30 bps
        })
        
        with patch('src.deploy.gate.get_canary_gate_thresholds') as mock_get:
            mock_get.return_value = {
                "max_reject_delta": 0.02,
                "max_latency_delta_ms": 50,
                "min_sample_fills": 100,  # Lower threshold to allow evaluation
                "drift_cap_pct": 5.0,
                "tail_min_sample": 200,
                "tail_p95_cap_ms": 50,
                "tail_p99_cap_ms": 100,
                "slo_tail_min_sample": 200,
                "slo_tail_p95_cap_ms": 50,
                "slo_tail_p99_cap_ms": 100,
                "markout_min_sample": 50,
                "markout_cap_bps_200": 0.5,
                "markout_cap_bps_500": 0.5,
            }
            
            ok, reasons, metrics = evaluate(self.canary_report, self.thresholds)
            
            # Should pass due to low samples (guard prevents evaluation)
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' not in canary_reasons
    
    def test_markout_guard_sufficient_samples(self):
        """Test that markout gate triggers when samples are sufficient."""
        # Set sufficient samples for both horizons
        self.canary_report["canary"].update({
            "markout_samples_200_blue": 100,  # Above 50 threshold
            "markout_samples_200_green": 100,
            "markout_samples_500_blue": 100,  # Above 50 threshold
            "markout_samples_500_green": 100,
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": -10.0,  # Green worse by 15 bps
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": -20.0,  # Green worse by 30 bps
        })
        
        with patch('src.deploy.gate.get_canary_gate_thresholds') as mock_get:
            mock_get.return_value = {
                "max_reject_delta": 0.02,
                "max_latency_delta_ms": 50,
                "min_sample_fills": 100,  # Lower threshold to allow evaluation
                "drift_cap_pct": 5.0,
                "tail_min_sample": 200,
                "tail_p95_cap_ms": 50,
                "tail_p99_cap_ms": 100,
                "slo_tail_min_sample": 200,
                "slo_tail_p95_cap_ms": 50,
                "slo_tail_p99_cap_ms": 100,
                "markout_min_sample": 50,
                "markout_cap_bps_200": 0.5,
                "markout_cap_bps_500": 0.5,
            }
            
            ok, reasons, metrics = evaluate(self.canary_report, self.thresholds)
            
            # Should fail due to markout regression (sufficient samples)
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons
    
    def test_markout_guard_custom_threshold(self):
        """Test that markout gate respects custom min_sample threshold."""
        # Set samples at custom threshold boundary
        self.canary_report["canary"].update({
            "markout_samples_200_blue": 75,  # At 75 threshold
            "markout_samples_200_green": 75,
            "markout_samples_500_blue": 75,
            "markout_samples_500_green": 75,
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": -10.0,  # Green worse by 15 bps
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": -20.0,  # Green worse by 30 bps
        })
        
        with patch('src.deploy.gate.get_canary_gate_thresholds') as mock_get:
            mock_get.return_value = {
                "max_reject_delta": 0.02,
                "max_latency_delta_ms": 50,
                "min_sample_fills": 100,  # Lower threshold to allow evaluation
                "drift_cap_pct": 5.0,
                "tail_min_sample": 200,
                "tail_p95_cap_ms": 50,
                "tail_p99_cap_ms": 100,
                "slo_tail_min_sample": 200,
                "slo_tail_p95_cap_ms": 50,
                "slo_tail_p99_cap_ms": 100,
                "markout_min_sample": 75,  # Custom threshold
                "markout_cap_bps_200": 0.5,
                "markout_cap_bps_500": 0.5,
            }
            
            ok, reasons, metrics = evaluate(self.canary_report, self.thresholds)
            
            # Should fail due to markout regression (samples meet custom threshold)
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons
    
    def test_markout_guard_edge_case_exact_threshold(self):
        """Test that markout gate works at exact threshold boundary."""
        # Set samples exactly at threshold
        self.canary_report["canary"].update({
            "markout_samples_200_blue": 50,  # Exactly at 50 threshold
            "markout_samples_200_green": 50,
            "markout_samples_500_blue": 50,
            "markout_samples_500_green": 50,
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": -10.0,  # Green worse by 15 bps
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": -20.0,  # Green worse by 30 bps
        })
        
        with patch('src.deploy.gate.get_canary_gate_thresholds') as mock_get:
            mock_get.return_value = {
                "max_reject_delta": 0.02,
                "max_latency_delta_ms": 50,
                "min_sample_fills": 100,  # Lower threshold to allow evaluation
                "drift_cap_pct": 5.0,
                "tail_min_sample": 200,
                "tail_p95_cap_ms": 50,
                "tail_p99_cap_ms": 100,
                "slo_tail_min_sample": 200,
                "slo_tail_p95_cap_ms": 50,
                "slo_tail_p99_cap_ms": 100,
                "markout_min_sample": 50,
                "markout_cap_bps_200": 0.5,
                "markout_cap_bps_500": 0.5,
            }
            
            ok, reasons, metrics = evaluate(self.canary_report, self.thresholds)
            
            # Should fail due to markout regression (samples meet threshold exactly)
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons

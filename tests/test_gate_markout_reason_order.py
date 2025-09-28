"""Test markout reason order in canary gate evaluation."""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


class TestGateMarkoutReasonOrder:
    """Test that markout_delta_exceeds appears in correct order."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.thresholds = GateThresholds()
        
        # Mock workflow report with champion metrics and canary data
        now_utc = datetime.now(timezone.utc)
        self.canary_report = {
            "symbol": "BTCUSDT",
            "metadata": {
                "created_at_utc": now_utc.isoformat()  # Current timestamp
            },
            "champion": {
                "aggregates": {
                    "hit_rate_mean": 0.95,
                    "maker_share_mean": 0.92,
                    "net_pnl_mean_usd": 100.0,
                    "cvar95_mean_usd": -5.0,  # Below 10.0 threshold
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
                # Markout data for gate evaluation
                "markout_samples_200_blue": 100,
                "markout_samples_200_green": 100,
                "markout_samples_500_blue": 100,
                "markout_samples_500_green": 100,
                "markout_200_blue_avg_bps": 5.0,
                "markout_200_green_avg_bps": -5.0,  # Green worse by 10 bps
                "markout_500_blue_avg_bps": 10.0,
                "markout_500_green_avg_bps": -10.0,  # Green worse by 20 bps
            }
        }
    
    def test_markout_reason_order(self):
        """Test that markout_delta_exceeds appears in correct order."""
        # Mock thresholds to ensure markout gate triggers
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
                # Markout thresholds
                "markout_min_sample": 50,
                "markout_cap_bps_200": 0.5,
                "markout_cap_bps_500": 0.5,
            }
            
            ok, reasons, metrics = evaluate(self.canary_report, self.thresholds)
            
            # Should fail due to markout regression
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            # Check order: markout should come after reject/latency deltas, before tail
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons
            
            # Verify order: killswitch_fired → rollout_drift → reject_delta_exceeds → 
            # latency_delta_exceeds → markout_delta_exceeds → latency_tail_* → slo_tail_*
            expected_order = [
                'reject_delta_exceeds',
                'latency_delta_exceeds', 
                'markout_delta_exceeds',
                'latency_tail_p95_exceeds',
                'latency_tail_p99_exceeds',
                'slo_tail_p95_breach',
                'slo_tail_p99_breach'
            ]
            
            # Check that markout appears in correct position
            markout_idx = canary_reasons.index('markout_delta_exceeds')
            reject_idx = canary_reasons.index('reject_delta_exceeds') if 'reject_delta_exceeds' in canary_reasons else -1
            latency_idx = canary_reasons.index('latency_delta_exceeds') if 'latency_delta_exceeds' in canary_reasons else -1
            tail_idx = canary_reasons.index('latency_tail_p95_exceeds') if 'latency_tail_p95_exceeds' in canary_reasons else len(canary_reasons)
            
            # markout should come after reject/latency deltas, before tail
            if reject_idx >= 0:
                assert markout_idx > reject_idx
            if latency_idx >= 0:
                assert markout_idx > latency_idx
            if tail_idx < len(canary_reasons):
                assert markout_idx < tail_idx
    
    def test_markout_reason_with_other_failures(self):
        """Test markout reason with other gate failures."""
        # Mock canary report with multiple failures
        self.canary_report["canary"].update({
            "killswitch_fired": True,
            "drift_alert": True,
            "rejects_green": 20,  # Higher reject rate
            "latency_ms_avg_green": 100.0,  # Higher latency
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
            
            # Should fail with multiple reasons
            assert not ok
            canary_reasons = metrics.get('canary_gate_reasons', [])
            
            # Check that all expected reasons are present
            expected_reasons = ['killswitch_fired', 'rollout_drift', 'reject_delta_exceeds', 
                              'latency_delta_exceeds', 'markout_delta_exceeds']
            
            for reason in expected_reasons:
                assert reason in canary_reasons, f"Missing reason: {reason}"
            
            # Verify order
            for i, reason in enumerate(expected_reasons):
                if reason in canary_reasons:
                    assert canary_reasons.index(reason) == i, f"Wrong order for {reason}"
    
    def test_markout_reason_not_triggered_when_ok(self):
        """Test that markout reason is not triggered when markout is good."""
        # Mock canary report with good markout
        self.canary_report["canary"].update({
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": 6.0,  # Green better
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": 12.0,  # Green better
        })
        
        with patch('src.deploy.thresholds.get_canary_gate_thresholds') as mock_get:
            mock_get.return_value = {
                "max_reject_delta": 0.02,
                "max_latency_delta_ms": 50,
                "min_sample_fills": 500,
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
            
            # Should pass (no markout regression)
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' not in canary_reasons

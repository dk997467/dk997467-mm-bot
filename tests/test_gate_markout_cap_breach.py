"""Test markout cap breach logic in canary gate evaluation."""

import pytest
from unittest.mock import Mock, patch
from src.deploy.gate import evaluate
from src.deploy.thresholds import GateThresholds


class TestGateMarkoutCapBreach:
    """Test that markout gate correctly evaluates cap breaches."""
    
    def setup_method(self):
        """Set up test fixtures."""
        from datetime import datetime, timezone
        
        self.thresholds = GateThresholds()
        
        # Base canary report with sufficient samples and metadata
        self.canary_report = {
            "symbol": "BTCUSDT",
            "metadata": {
                "created_at_utc": datetime.now(timezone.utc).isoformat()
            },
            "champion": {
                "aggregates": {
                    "hit_rate_mean": 0.95,
                    "maker_share_mean": 0.95,
                    "net_pnl_mean_usd": 10.0,
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
                # Sufficient samples for markout evaluation
                "markout_samples_200_blue": 100,
                "markout_samples_200_green": 100,
                "markout_samples_500_blue": 100,
                "markout_samples_500_green": 100,
            }
        }
    
    def test_markout_breach_200ms_only(self):
        """Test that markout gate triggers when only 200ms breaches cap."""
        # Set 200ms to breach, 500ms to be ok
        self.canary_report["canary"].update({
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": -1.0,  # Delta: -6.0 bps (breaches -0.5 cap)
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": 9.0,   # Delta: -1.0 bps (within -0.5 cap)
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
            
            # Should fail due to 200ms markout breach
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons
    
    def test_markout_breach_500ms_only(self):
        """Test that markout gate triggers when only 500ms breaches cap."""
        # Set 200ms to be ok, 500ms to breach
        self.canary_report["canary"].update({
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": 4.6,   # Delta: -0.4 bps (within -0.5 cap)
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": -5.0,  # Delta: -15.0 bps (breaches -0.5 cap)
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
            
            # Should fail due to 500ms markout breach
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons
    
    def test_markout_breach_both_horizons(self):
        """Test that markout gate triggers when both horizons breach cap."""
        # Set both horizons to breach
        self.canary_report["canary"].update({
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": -2.0,  # Delta: -7.0 bps (breaches -0.5 cap)
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": -8.0,  # Delta: -18.0 bps (breaches -0.5 cap)
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
            
            # Should fail due to both markout breaches
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons
    
    def test_markout_no_breach(self):
        """Test that markout gate doesn't trigger when no horizon breaches cap."""
        # Set both horizons to be within cap
        self.canary_report["canary"].update({
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": 4.6,   # Delta: -0.4 bps (within -0.5 cap)
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": 9.6,   # Delta: -0.4 bps (within -0.5 cap)
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
            
            # Should pass (no markout breaches)
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' not in canary_reasons
    
    def test_markout_breach_edge_case_exact_cap(self):
        """Test that markout gate triggers at exact cap boundary."""
        # Set slightly below cap boundary to trigger breach
        self.canary_report["canary"].update({
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": 4.4,   # Delta: -0.6 bps (below -0.5 cap)
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": 9.4,   # Delta: -0.6 bps (below -0.5 cap)
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
            
            # Should fail due to cap breach (below threshold)
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons
    
    def test_markout_breach_custom_caps(self):
        """Test that markout gate respects custom cap thresholds."""
        # Set custom caps and breach values
        self.canary_report["canary"].update({
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": 2.0,   # Delta: -3.0 bps
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": 5.0,   # Delta: -5.0 bps
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
                "markout_cap_bps_200": 2.0,  # Custom cap: -2.0 bps
                "markout_cap_bps_500": 3.0,  # Custom cap: -3.0 bps
            }
            
            ok, reasons, metrics = evaluate(self.canary_report, self.thresholds)
            
            # 200ms: -3.0 < -2.0 (breaches), 500ms: -5.0 < -3.0 (breaches)
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons
    
    def test_markout_breach_green_better(self):
        """Test that markout gate doesn't trigger when green is better than blue."""
        # Set green to be better than blue (positive deltas)
        self.canary_report["canary"].update({
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": 8.0,   # Delta: +3.0 bps (green better)
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": 15.0,  # Delta: +5.0 bps (green better)
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
            
            # Should pass (green is better, no regression)
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' not in canary_reasons
    
    def test_markout_breach_mixed_signals(self):
        """Test that markout gate triggers with mixed positive/negative deltas."""
        # Set mixed signals: 200ms green better, 500ms green worse
        self.canary_report["canary"].update({
            "markout_200_blue_avg_bps": 5.0,
            "markout_200_green_avg_bps": 8.0,   # Delta: +3.0 bps (green better)
            "markout_500_blue_avg_bps": 10.0,
            "markout_500_green_avg_bps": -5.0,  # Delta: -15.0 bps (green worse, breaches cap)
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
            
            # Should fail due to 500ms breach (OR logic)
            assert not ok
            assert "canary:markout_delta_exceeds" in reasons
            
            canary_reasons = metrics.get('canary_gate_reasons', [])
            assert 'markout_delta_exceeds' in canary_reasons

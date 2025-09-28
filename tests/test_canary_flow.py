"""
Tests for F2 canary deployment flow.
"""

import pytest
import json
import time
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from src.deploy.rollout import (
    monitor_metrics, apply_patch, do_rollback, parse_prom_metrics,
    compute_slope, _http_get_json, _http_post_json, _http_get_text
)
from src.deploy.thresholds import GateThresholds


class TestCanaryFlow:
    """Test F2 canary deployment scenarios."""

    def create_mock_thresholds(self):
        """Create mock thresholds for testing."""
        return GateThresholds(
            min_hit_rate=0.01,
            min_maker_share=0.90,
            max_sim_live_divergence=0.15
        )

    def test_parse_prom_metrics(self):
        """Test Prometheus metrics parsing."""
        metrics_text = """
        # HELP risk_paused Risk pause status
        risk_paused 0
        cancel_rate_per_sec 1.5
        rest_error_rate 0.002
        net_pnl_total_usd 125.75
        hit_rate_proxy 0.25
        cfg_max_cancel_per_sec 100.0
        # Comment line
        invalid_line_no_number abc
        """
        
        metrics = parse_prom_metrics(metrics_text)
        
        assert metrics['risk_paused'] == 0.0
        assert metrics['cancel_rate_per_sec'] == 1.5
        assert metrics['rest_error_rate'] == 0.002
        assert metrics['net_pnl_total_usd'] == 125.75
        assert metrics['hit_rate_proxy'] == 0.25
        assert metrics['cfg_max_cancel_per_sec'] == 100.0
        assert 'invalid_line_no_number' not in metrics

    def test_compute_slope_basic(self):
        """Test basic slope computation."""
        # Linear increase: 100, 110, 120 over 2 minutes
        series = [
            (time.time() - 120, 100.0),  # 2 min ago
            (time.time() - 60, 110.0),   # 1 min ago  
            (time.time(), 120.0)         # now
        ]
        
        slope = compute_slope(series, window_sec=300)
        
        # Should be approximately +10 per minute
        assert 9.0 <= slope <= 11.0

    def test_compute_slope_negative(self):
        """Test negative slope computation."""
        # Linear decrease: 120, 110, 100 over 2 minutes
        series = [
            (time.time() - 120, 120.0),
            (time.time() - 60, 110.0),
            (time.time(), 100.0)
        ]
        
        slope = compute_slope(series, window_sec=300)
        
        # Should be approximately -10 per minute
        assert -11.0 <= slope <= -9.0

    def test_compute_slope_insufficient_data(self):
        """Test slope computation with insufficient data."""
        # Single point
        series = [(time.time(), 100.0)]
        slope = compute_slope(series, window_sec=300)
        assert slope == 0.0
        
        # Empty series
        series = []
        slope = compute_slope(series, window_sec=300)
        assert slope == 0.0

    @patch('src.deploy.rollout._http_get_text')
    def test_monitor_metrics_healthy(self, mock_http_get_text):
        """Test monitoring with healthy metrics (no degradation)."""
        # Mock healthy metrics responses
        healthy_metrics = """
        risk_paused 0
        cancel_rate_per_sec 2.0
        rest_error_rate 0.005
        net_pnl_total_usd 100.0
        cfg_max_cancel_per_sec 100.0
        """
        
        mock_http_get_text.return_value = healthy_metrics
        thresholds = self.create_mock_thresholds()
        
        # Very short monitoring period for test
        ok, reasons, stats = monitor_metrics(
            "http://localhost/metrics", 
            minutes=0.05,  # 3 seconds
            thresholds=thresholds,
            poll_sec=1
        )
        
        assert ok is True
        assert len(reasons) == 0
        assert stats['polls_completed'] >= 2
        assert 'max_values' in stats
        assert 'last_values' in stats

    @patch('src.deploy.rollout._http_get_text')
    def test_monitor_metrics_degraded(self, mock_http_get_text):
        """Test monitoring with degraded metrics (triggers rollback)."""
        # Mock degraded metrics responses (high cancel rate)
        degraded_metrics = """
        risk_paused 0
        cancel_rate_per_sec 95.0
        rest_error_rate 0.002
        net_pnl_total_usd 100.0
        cfg_max_cancel_per_sec 100.0
        """
        
        mock_http_get_text.return_value = degraded_metrics
        thresholds = self.create_mock_thresholds()
        
        # Monitor for short period
        ok, reasons, stats = monitor_metrics(
            "http://localhost/metrics",
            minutes=0.1,  # 6 seconds
            thresholds=thresholds,
            poll_sec=1
        )
        
        assert ok is False
        assert len(reasons) > 0
        assert any("Cancel rate too high" in reason for reason in reasons)
        assert 'degraded_rules' in stats
        assert 'high_cancel_rate' in stats['degraded_rules']

    @patch('src.deploy.rollout._http_get_text')
    def test_monitor_metrics_risk_paused(self, mock_http_get_text):
        """Test monitoring with risk_paused trigger."""
        # Risk paused should immediately trigger
        risk_paused_metrics = """
        risk_paused 1
        cancel_rate_per_sec 1.0
        rest_error_rate 0.001
        net_pnl_total_usd 100.0
        cfg_max_cancel_per_sec 100.0
        """
        
        mock_http_get_text.return_value = risk_paused_metrics
        thresholds = self.create_mock_thresholds()
        
        ok, reasons, stats = monitor_metrics(
            "http://localhost/metrics",
            minutes=0.1,
            thresholds=thresholds,
            poll_sec=1
        )
        
        assert ok is False
        assert any("Risk paused" in reason for reason in reasons)

    @patch('src.deploy.rollout._http_post_json')
    def test_apply_patch(self, mock_http_post_json):
        """Test patch application."""
        mock_response = {
            "ok": True,
            "applied": True,
            "cfg_hash_before": "old_hash",
            "cfg_hash_after": "new_hash"
        }
        mock_http_post_json.return_value = mock_response
        
        patch_data = {"levels_per_side": 3, "k_vola_spread": 1.5}
        result = apply_patch("http://localhost", patch_data, "BTCUSDT", dry_run=False)
        
        assert result == mock_response
        mock_http_post_json.assert_called_once_with(
            "http://localhost/admin/reload",
            {
                "symbol": "BTCUSDT",
                "patch": patch_data,
                "dry_run": False
            },
            timeout=10
        )

    @patch('src.deploy.rollout._http_post_json')
    def test_do_rollback(self, mock_http_post_json):
        """Test configuration rollback."""
        mock_response = {
            "ok": True,
            "rolled_back": True,
            "cfg_hash_before": "canary_hash",
            "cfg_hash_after": "baseline_hash"
        }
        mock_http_post_json.return_value = mock_response
        
        result = do_rollback("http://localhost")
        
        assert result == mock_response
        mock_http_post_json.assert_called_once_with(
            "http://localhost/admin/rollback",
            {},
            timeout=10
        )

    @patch('src.deploy.rollout._http_get_text')
    def test_monitor_metrics_network_error_recovery(self, mock_http_get_text):
        """Test monitoring recovers from network errors."""
        # First call fails, second succeeds
        mock_http_get_text.side_effect = [
            Exception("Network error"),
            """
            risk_paused 0
            cancel_rate_per_sec 1.0
            rest_error_rate 0.001
            net_pnl_total_usd 100.0
            cfg_max_cancel_per_sec 100.0
            """,
            """
            risk_paused 0
            cancel_rate_per_sec 1.0
            rest_error_rate 0.001
            net_pnl_total_usd 101.0
            cfg_max_cancel_per_sec 100.0
            """
        ]
        
        thresholds = self.create_mock_thresholds()
        
        ok, reasons, stats = monitor_metrics(
            "http://localhost/metrics",
            minutes=0.05,  # Very short
            thresholds=thresholds,
            poll_sec=1
        )
        
        # Should succeed despite initial network error
        assert ok is True
        assert len(reasons) == 0

    @patch('src.deploy.rollout._http_get_text') 
    def test_monitor_metrics_pnl_slope_degradation(self, mock_http_get_text):
        """Test PnL slope degradation detection."""
        # Simulate declining PnL over multiple polls
        pnl_values = [100.0, 98.0, 96.0, 94.0, 92.0]  # Strong decline
        
        def side_effect(*args, **kwargs):
            pnl = pnl_values.pop(0) if pnl_values else 90.0
            return f"""
            risk_paused 0
            cancel_rate_per_sec 1.0
            rest_error_rate 0.001
            net_pnl_total_usd {pnl}
            cfg_max_cancel_per_sec 100.0
            """
        
        mock_http_get_text.side_effect = side_effect
        thresholds = self.create_mock_thresholds()
        
        ok, reasons, stats = monitor_metrics(
            "http://localhost/metrics",
            minutes=0.15,  # Longer period to accumulate PnL history
            thresholds=thresholds,
            poll_sec=1
        )
        
        # Should detect negative PnL trend
        assert ok is False
        assert any("Negative PnL trend" in reason for reason in reasons)


class TestHTTPHelpers:
    """Test HTTP helper functions."""

    @patch('urllib.request.urlopen')
    def test_http_get_json_success(self, mock_urlopen):
        """Test successful JSON GET request."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b'{"status": "ok", "value": 42}'
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = _http_get_json("http://localhost/api")
        
        assert result == {"status": "ok", "value": 42}

    @patch('urllib.request.urlopen')
    def test_http_get_json_connection_error(self, mock_urlopen):
        """Test connection error handling."""
        mock_urlopen.side_effect = Exception("Connection failed")
        
        with pytest.raises(ConnectionError, match="Failed to connect"):
            _http_get_json("http://localhost/api")

    @patch('urllib.request.urlopen')
    def test_http_post_json_success(self, mock_urlopen):
        """Test successful JSON POST request."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b'{"applied": true}'
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        payload = {"key": "value", "number": 123}
        result = _http_post_json("http://localhost/api", payload)
        
        assert result == {"applied": True}

    @patch('urllib.request.urlopen')
    def test_http_get_text_success(self, mock_urlopen):
        """Test successful text GET request."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.read.return_value = b'metric_name 42.5\nother_metric 10'
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = _http_get_text("http://localhost/metrics")
        
        assert result == "metric_name 42.5\nother_metric 10"

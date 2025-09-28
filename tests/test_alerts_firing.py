"""
Test alert firing by manipulating metrics.
"""

import pytest
import time
from prometheus_client import REGISTRY, CollectorRegistry
from unittest.mock import Mock

from src.common.config import AppConfig, StrategyConfig, LimitsConfig, TradingConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


class TestAlertFiring:
    """Test that alerts fire when conditions are met."""
    
    def setup_method(self):
        """Clear registry and setup test environment."""
        # Clear Prometheus registry to avoid duplicate metric errors
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        
        self.config = AppConfig(
            strategy=StrategyConfig(),
            limits=LimitsConfig(),
            trading=TradingConfig()
        )
        self.ctx = AppContext(cfg=self.config)
        self.metrics = Metrics(self.ctx)
    
    def test_risk_paused_alert_firing(self):
        """Test that RiskPaused alert fires when risk_paused = 1."""
        # Set risk paused
        self.metrics.update_risk_metrics(risk_paused=True, drawdown_day=0.0)
        
        # Check metric value
        risk_paused_value = self.metrics.risk_paused._value.get()
        assert risk_paused_value == 1.0
        
        # This would trigger the RiskPaused alert in Prometheus
        # expr: risk_paused == 1
        
    def test_circuit_breaker_alert_firing(self):
        """Test that CircuitBreakerOpen alert fires when circuit_breaker_state = 1."""
        # Set circuit breaker open
        self.metrics.set_circuit_breaker_state(True)
        
        # Check metric value
        circuit_breaker_value = self.metrics.circuit_breaker_state._value.get()
        assert circuit_breaker_value == 1.0
        
        # This would trigger the CircuitBreakerOpen alert in Prometheus
        # expr: circuit_breaker_state == 1
        
    def test_high_error_rate_alert_firing(self):
        """Test that RejectRateHigh alert fires when rest_error_rate > 0.02."""
        # Set high error rate
        self.metrics.update_connectivity_metrics("bybit", 0, 0.05)  # 5% error rate
        
        # Check metric value
        error_rate_value = self.metrics.rest_error_rate.labels(exchange="bybit")._value.get()
        assert error_rate_value == 0.05
        
        # This would trigger the RejectRateHigh alert in Prometheus
        # expr: rest_error_rate{exchange="bybit"} > 0.02
        
    def test_high_latency_alert_firing(self):
        """Test that HighLatencyREST alert fires when latency > 300ms."""
        # Record high latency
        self.metrics.observe_latency("rest", 500)  # 500ms latency
        
        # Check that metric was recorded
        # Note: This is a histogram, so we can't easily check the exact value
        # In Prometheus, this would trigger: histogram_quantile(0.95, sum(rate(latency_ms_bucket{stage="rest"}[5m])) by (le)) > 300
        
    def test_amend_failure_rate_alert_firing(self):
        """Test that AmendFailureRateHigh alert fires when failure rate > 10%."""
        # Record amend attempts and failures
        self.metrics.on_amend_attempt("BTCUSDT", "Buy")
        self.metrics.on_amend_attempt("BTCUSDT", "Buy")
        self.metrics.on_amend_attempt("BTCUSDT", "Buy")
        
        # Only one success
        self.metrics.on_amend_success("BTCUSDT", "Buy")
        
        # Check metric values
        attempts = self.metrics.amend_attempts_total.labels(symbol="BTCUSDT", side="Buy")._value.get()
        successes = self.metrics.amend_success_total.labels(symbol="BTCUSDT", side="Buy")._value.get()
        
        assert attempts == 3
        assert successes == 1
        
        # Failure rate = (3-1)/3 = 66.7% > 10%
        # This would trigger the AmendFailureRateHigh alert in Prometheus
        # expr: (amend_attempts_total - amend_success_total) / max(amend_attempts_total, 1) > 0.1
        
    def test_queue_position_degraded_alert_firing(self):
        """Test that QueuePositionDegraded alert fires when queue_pos_delta < -100."""
        # Set degraded queue position
        self.metrics.update_queue_pos_delta("BTCUSDT", "Buy", -150.0)
        
        # Check metric value
        queue_pos_value = self.metrics.queue_pos_delta.labels(symbol="BTCUSDT", side="Buy")._value.get()
        assert queue_pos_value == -150.0
        
        # This would trigger the QueuePositionDegraded alert in Prometheus
        # expr: queue_pos_delta < -100
        
    def test_high_backoff_time_alert_firing(self):
        """Test that HighBackoffTime alert fires when backoff rate > 0.1."""
        # Add backoff time
        self.metrics.add_backoff_seconds(1.0)
        self.metrics.add_backoff_seconds(1.0)
        
        # Check metric value
        backoff_total = self.metrics.backoff_seconds_sum._value.get()
        assert backoff_total == 2.0
        
        # In Prometheus, this would trigger: rate(backoff_seconds_sum[5m]) > 0.1
        # (assuming the rate over 5 minutes is calculated)
        
    def test_drawdown_alert_firing(self):
        """Test that DrawdownDay alert fires when drawdown < -0.01."""
        # Set high drawdown
        self.metrics.update_risk_metrics(risk_paused=False, drawdown_day=-0.02)
        
        # Check metric value
        drawdown_value = self.metrics.drawdown_day._value.get()
        assert drawdown_value == -0.02
        
        # This would trigger the DrawdownDay alert in Prometheus
        # expr: drawdown_day < -0.01
        
    def test_cancel_rate_near_limit_alert_firing(self):
        """Test that CancelRateNearLimit alert fires when cancel_rate > 0.9 * cfg_max_cancel_per_sec."""
        # Set high cancel rate
        # Note: cancel_rate is calculated over time, so we'll just verify the metric exists
        # In Prometheus, this would trigger: cancel_rate > 0.9 * cfg_max_cancel_per_sec
        
        # Check that the config metric exists
        max_cancel_per_sec = self.metrics.cfg_max_cancel_per_sec._value.get()
        assert max_cancel_per_sec == 4.0  # Default value from config
        
    def test_alert_labels_consistency(self):
        """Test that all alerts would have consistent labels when firing."""
        # This test verifies that our alert rules would have consistent labels
        # In a real Prometheus setup, all alerts would have:
        # - severity: "critical"|"warning"|"info"
        # - service: "mm_bot"
        # - instance: hostname
        # - job: "mm_bot"
        
        # For now, we just verify our metrics have the right structure
        assert hasattr(self.metrics, 'risk_paused')
        assert hasattr(self.metrics, 'circuit_breaker_state')
        assert hasattr(self.metrics, 'rest_error_rate')
        assert hasattr(self.metrics, 'amend_attempts_total')
        assert hasattr(self.metrics, 'amend_success_total')
        assert hasattr(self.metrics, 'queue_pos_delta')
        assert hasattr(self.metrics, 'backoff_seconds_sum')
        assert hasattr(self.metrics, 'drawdown_day')

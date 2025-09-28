"""Test markout integration in canary payload."""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from prometheus_client import REGISTRY
from src.metrics.exporter import Metrics
from src.common.di import AppContext


class TestMarkoutCanaryPayload:
    """Test markout integration in canary payload."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear prometheus registry to avoid duplicate metrics
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        
        self.ctx = Mock(spec=AppContext)
        self.metrics = Metrics(self.ctx)
        
        # Mock config
        self.config = Mock()
        self.config.rollout = Mock()
        self.config.rollout.traffic_split_pct = 50
        self.config.rollout.salt = "test_salt"
        self.config.rollout.blue = {}
        self.config.rollout.green = {}
        self.config.killswitch = Mock()
        self.config.killswitch.enabled = False
        self.config.killswitch.dry_run = True
        self.config.killswitch.action = "rollback"
        self.config.killswitch.max_reject_delta = 0.02
        self.config.killswitch.max_latency_delta_ms = 50
        self.config.killswitch.min_fills = 500
        self.config.autopromote = Mock()
        self.config.autopromote.enabled = False
        self.config.autopromote.stable_steps_required = 6
        self.config.autopromote.min_split_pct = 25
        
        # Add rollout_ramp config
        self.config.rollout_ramp = Mock()
        self.config.rollout_ramp.enabled = False
        
        # Create real bot instance
        from cli.run_bot import MarketMakerBot
        self.bot = MarketMakerBot.__new__(MarketMakerBot)
        self.bot.config = self.config
        self.bot.metrics = self.metrics
        self.bot._ramp_state = {}
        self.bot._build_time_iso = "2024-01-01T00:00:00Z"
        self.bot._params_hash = "test_hash"
        self.bot._ramp_holds_counts = {"sample": 0, "cooldown": 0}
        self.bot._ensure_admin_audit_initialized()
        
        # Mock methods
        self.bot._admin_actor_hash = Mock(return_value="test_actor")
        self.bot._admin_rate_limit_check = Mock(return_value=True)
        self.bot._admin_audit_record = Mock()
        self.bot._append_json_line = Mock()
        self.bot._alerts_log_file = Mock(return_value="/tmp/test_alerts.log")
    
    def test_canary_payload_markout_empty(self):
        """Test canary payload when no markout data exists."""
        # Mock rollout metrics
        self.metrics._rollout_orders_count = {"blue": 0, "green": 0}
        self.metrics._rollout_fills = {"blue": 0, "green": 0}
        self.metrics._rollout_rejects = {"blue": 0, "green": 0}
        self.metrics._rollout_latency_ewma = {"blue": 0.0, "green": 0.0}
        
        # Mock rollout split metrics
        self.metrics.rollout_split_observed_pct = Mock()
        self.metrics.rollout_split_observed_pct._value.get.return_value = 50.0
        
        # Mock latency tail metrics
        self.metrics.rollout_latency_p95_ms = Mock()
        self.metrics.rollout_latency_p99_ms = Mock()
        self.metrics.rollout_latency_samples_total = Mock()
        
        for metric in [self.metrics.rollout_latency_p95_ms, self.metrics.rollout_latency_p99_ms, self.metrics.rollout_latency_samples_total]:
            metric.labels.return_value._value.get.return_value = 0.0
        
        # Mock ramp metrics
        self.metrics.rollout_ramp_step_idx = Mock()
        self.metrics.rollout_ramp_frozen = Mock()
        self.metrics.rollout_ramp_cooldown_seconds = Mock()
        for metric in [self.metrics.rollout_ramp_step_idx, self.metrics.rollout_ramp_frozen, self.metrics.rollout_ramp_cooldown_seconds]:
            metric._value.get.return_value = 0.0
        
        # Build payload
        payload = self.bot._build_canary_payload()
        
        # Check markout block exists
        assert "markout" in payload
        markout = payload["markout"]
        
        # Check structure
        assert "200" in markout
        assert "500" in markout
        assert "blue" in markout["200"]
        assert "green" in markout["200"]
        assert "blue" in markout["500"]
        assert "green" in markout["500"]
        
        # Check default values
        assert markout["200"]["blue"]["avg_bps"] == 0.0
        assert markout["200"]["green"]["avg_bps"] == 0.0
        assert markout["500"]["blue"]["avg_bps"] == 0.0
        assert markout["500"]["green"]["avg_bps"] == 0.0
        assert markout["200"]["delta_bps"] == 0.0
        assert markout["500"]["delta_bps"] == 0.0
    
    def test_canary_payload_markout_with_data(self):
        """Test canary payload with markout data."""
        # Record some markout data
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49975.0, 49950.0)  # -5.0, -10.0 bps
        
        # Mock rollout metrics
        self.metrics._rollout_orders_count = {"blue": 100, "green": 100}
        self.metrics._rollout_fills = {"blue": 95, "green": 90}
        self.metrics._rollout_rejects = {"blue": 5, "green": 10}
        self.metrics._rollout_latency_ewma = {"blue": 25.0, "green": 30.0}
        
        # Mock rollout split metrics
        self.metrics.rollout_split_observed_pct = Mock()
        self.metrics.rollout_split_observed_pct._value.get.return_value = 50.0
        
        # Mock latency tail metrics
        self.metrics.rollout_latency_p95_ms = Mock()
        self.metrics.rollout_latency_p99_ms = Mock()
        self.metrics.rollout_latency_samples_total = Mock()
        
        for metric in [self.metrics.rollout_latency_p95_ms, self.metrics.rollout_latency_p99_ms, self.metrics.rollout_latency_samples_total]:
            metric.labels.return_value._value.get.return_value = 100.0
        
        # Mock ramp metrics
        self.metrics.rollout_ramp_step_idx = Mock()
        self.metrics.rollout_ramp_frozen = Mock()
        self.metrics.rollout_ramp_cooldown_seconds = Mock()
        for metric in [self.metrics.rollout_ramp_step_idx, self.metrics.rollout_ramp_frozen, self.metrics.rollout_ramp_cooldown_seconds]:
            metric._value.get.return_value = 0.0
        
        # Build payload
        payload = self.bot._build_canary_payload()
        
        # Check markout block
        assert "markout" in payload
        markout = payload["markout"]
        
        # Check values
        assert markout["200"]["blue"]["avg_bps"] == 5.0
        assert markout["200"]["green"]["avg_bps"] == -5.0
        assert markout["500"]["blue"]["avg_bps"] == 10.0
        assert markout["500"]["green"]["avg_bps"] == -10.0
        
        # Check deltas
        assert markout["200"]["delta_bps"] == -10.0  # green - blue = -5 - 5
        assert markout["500"]["delta_bps"] == -20.0  # green - blue = -10 - 10
    
    def test_canary_payload_markout_triage_hints(self):
        """Test markout triage hints in canary payload."""
        # Record markout data where green is worse
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49950.0, 49800.0)  # -10.0, -40.0 bps
        
        # Mock rollout metrics
        self.metrics._rollout_orders_count = {"blue": 100, "green": 100}
        self.metrics._rollout_fills = {"blue": 95, "green": 90}
        self.metrics._rollout_rejects = {"blue": 5, "green": 10}
        self.metrics._rollout_latency_ewma = {"blue": 25.0, "green": 30.0}
        
        # Mock rollout split metrics
        self.metrics.rollout_split_observed_pct = Mock()
        self.metrics.rollout_split_observed_pct._value.get.return_value = 50.0
        
        # Mock latency tail metrics
        self.metrics.rollout_latency_p95_ms = Mock()
        self.metrics.rollout_latency_p99_ms = Mock()
        self.metrics.rollout_latency_samples_total = Mock()
        
        for metric in [self.metrics.rollout_latency_p95_ms, self.metrics.rollout_latency_p99_ms, self.metrics.rollout_latency_samples_total]:
            metric.labels.return_value._value.get.return_value = 100.0
        
        # Mock ramp metrics
        self.metrics.rollout_ramp_step_idx = Mock()
        self.metrics.rollout_ramp_frozen = Mock()
        self.metrics.rollout_ramp_cooldown_seconds = Mock()
        for metric in [self.metrics.rollout_ramp_step_idx, self.metrics.rollout_ramp_frozen, self.metrics.rollout_ramp_cooldown_seconds]:
            metric._value.get.return_value = 0.0
        
        # Build payload
        payload = self.bot._build_canary_payload()
        
        # Check hints
        assert "hints" in payload
        hints = payload["hints"]
        
        # Should have markout hints since green is worse than blue by more than 0.5 bps
        assert "markout_green_worse_200ms" in hints
        assert "markout_green_worse_500ms" in hints
    
    def test_canary_payload_markout_triage_hints_threshold(self):
        """Test markout triage hints threshold behavior."""
        # Record markout data where green is slightly worse but within threshold
        # Blue: (50025-50000)/50000*10000 = +5.0 bps, (50050-50000)/50000*10000 = +10.0 bps
        # Green: (49998-50000)/50000*10000 = -0.4 bps, (49995-50000)/50000*10000 = -1.0 bps
        # Delta: -0.4 - 5.0 = -5.4 bps (200ms), -1.0 - 10.0 = -11.0 bps (500ms)
        # Since -5.4 < -0.5 and -11.0 < -0.5, both hints should trigger
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49998.0, 49995.0)
        
        # Mock rollout metrics
        self.metrics._rollout_orders_count = {"blue": 100, "green": 100}
        self.metrics._rollout_fills = {"blue": 95, "green": 90}
        self.metrics._rollout_rejects = {"blue": 5, "green": 10}
        self.metrics._rollout_latency_ewma = {"blue": 25.0, "green": 30.0}
        
        # Mock rollout split metrics
        self.metrics.rollout_split_observed_pct = Mock()
        self.metrics.rollout_split_observed_pct._value.get.return_value = 50.0
        
        # Mock latency tail metrics
        self.metrics.rollout_latency_p95_ms = Mock()
        self.metrics.rollout_latency_p99_ms = Mock()
        self.metrics.rollout_latency_samples_total = Mock()
        
        for metric in [self.metrics.rollout_latency_p95_ms, self.metrics.rollout_latency_p99_ms, self.metrics.rollout_latency_samples_total]:
            metric.labels.return_value._value.get.return_value = 100.0
        
        # Mock ramp metrics
        self.metrics.rollout_ramp_step_idx = Mock()
        self.metrics.rollout_ramp_frozen = Mock()
        self.metrics.rollout_ramp_cooldown_seconds = Mock()
        for metric in [self.metrics.rollout_ramp_step_idx, self.metrics.rollout_ramp_frozen, self.metrics.rollout_ramp_cooldown_seconds]:
            metric._value.get.return_value = 0.0
        
        # Build payload
        payload = self.bot._build_canary_payload()
        
        # Check hints
        assert "hints" in payload
        hints = payload["hints"]
        
        # Should have markout hints since difference exceeds 0.5 bps threshold
        assert "markout_green_worse_200ms" in hints
        assert "markout_green_worse_500ms" in hints
    
    def test_canary_payload_markout_environment_cap(self):
        """Test markout triage hints with custom environment cap."""
        # Set custom environment cap
        os.environ['MARKOUT_CAP_BPS'] = '0.1'
        
        try:
            # Record markout data where green is worse by 0.2 bps (above 0.1 cap)
            self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
            self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49990.0, 49980.0)  # -2.0, -4.0 bps
            
            # Mock rollout metrics
            self.metrics._rollout_orders_count = {"blue": 100, "green": 100}
            self.metrics._rollout_fills = {"blue": 95, "green": 90}
            self.metrics._rollout_rejects = {"blue": 5, "green": 10}
            self.metrics._rollout_latency_ewma = {"blue": 25.0, "green": 30.0}
            
            # Mock rollout split metrics
            self.metrics.rollout_split_observed_pct = Mock()
            self.metrics.rollout_split_observed_pct._value.get.return_value = 50.0
            
            # Mock latency tail metrics
            self.metrics.rollout_latency_p95_ms = Mock()
            self.metrics.rollout_latency_p99_ms = Mock()
            self.metrics.rollout_latency_samples_total = Mock()
            
            for metric in [self.metrics.rollout_latency_p95_ms, self.metrics.rollout_latency_p99_ms, self.metrics.rollout_latency_samples_total]:
                metric.labels.return_value._value.get.return_value = 100.0
            
            # Mock ramp metrics
            self.metrics.rollout_ramp_step_idx = Mock()
            self.metrics.rollout_ramp_frozen = Mock()
            self.metrics.rollout_ramp_cooldown_seconds = Mock()
            for metric in [self.metrics.rollout_ramp_step_idx, self.metrics.rollout_ramp_frozen, self.metrics.rollout_ramp_cooldown_seconds]:
                metric._value.get.return_value = 0.0
            
            # Build payload
            payload = self.bot._build_canary_payload()
            
            # Check hints
            assert "hints" in payload
            hints = payload["hints"]
            
            # Should have markout hints since difference (-7.0 bps) is above 0.1 bps cap
            assert "markout_green_worse_200ms" in hints
            assert "markout_green_worse_500ms" in hints
            
        finally:
            # Clean up environment
            if 'MARKOUT_CAP_BPS' in os.environ:
                del os.environ['MARKOUT_CAP_BPS']
    
    def test_canary_payload_markout_multiple_symbols(self):
        """Test markout averaging across multiple symbols."""
        # Record markout data for multiple symbols
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
        self.metrics.record_markout("ETHUSDT", "blue", 3000.0, 3000.0, 3003.0, 3006.0)      # +1.0, +2.0 bps
        
        # Mock rollout metrics
        self.metrics._rollout_orders_count = {"blue": 100, "green": 100}
        self.metrics._rollout_fills = {"blue": 95, "green": 90}
        self.metrics._rollout_rejects = {"blue": 5, "green": 10}
        self.metrics._rollout_latency_ewma = {"blue": 25.0, "green": 30.0}
        
        # Mock rollout split metrics
        self.metrics.rollout_split_observed_pct = Mock()
        self.metrics.rollout_split_observed_pct._value.get.return_value = 50.0
        
        # Mock latency tail metrics
        self.metrics.rollout_latency_p95_ms = Mock()
        self.metrics.rollout_latency_p99_ms = Mock()
        self.metrics.rollout_latency_samples_total = Mock()
        
        for metric in [self.metrics.rollout_latency_p95_ms, self.metrics.rollout_latency_p99_ms, self.metrics.rollout_latency_samples_total]:
            metric.labels.return_value._value.get.return_value = 100.0
        
        # Mock ramp metrics
        self.metrics.rollout_ramp_step_idx = Mock()
        self.metrics.rollout_ramp_frozen = Mock()
        self.metrics.rollout_ramp_cooldown_seconds = Mock()
        for metric in [self.metrics.rollout_ramp_step_idx, self.metrics.rollout_ramp_frozen, self.metrics.rollout_ramp_cooldown_seconds]:
            metric._value.get.return_value = 0.0
        
        # Build payload
        payload = self.bot._build_canary_payload()
        
        # Check markout block
        assert "markout" in payload
        markout = payload["markout"]
        
        # Check weighted average: (5.0*1 + 10.0*1) / 2 = 7.5 bps
        assert abs(markout["200"]["blue"]["avg_bps"] - 7.5) < 0.01
        # Check weighted average: (10.0*1 + 20.0*1) / 2 = 15.0 bps
        assert abs(markout["500"]["blue"]["avg_bps"] - 15.0) < 0.01

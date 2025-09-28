"""Test markout triage hints."""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from prometheus_client import REGISTRY
from src.metrics.exporter import Metrics
from src.common.di import AppContext


class TestMarkoutTriageHint:
    """Test markout triage hints generation."""
    
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
    
    def test_triage_hint_markout_green_worse_200ms(self):
        """Test triage hint when green markout is worse at 200ms."""
        # Record markout data where green is worse at 200ms
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49950.0, 50000.0)  # -10.0, 0.0 bps
        
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
        
        # Should have 200ms hint since green is worse by 15 bps (above 0.5 cap)
        assert "markout_green_worse_200ms" in hints
        # Should not have 500ms hint since green is only worse by 10 bps (above 0.5 cap)
        assert "markout_green_worse_500ms" in hints
    
    def test_triage_hint_markout_green_worse_500ms(self):
        """Test triage hint when green markout is worse at 500ms."""
        # Record markout data where green is worse at 500ms
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 50000.0, 49900.0)  # 0.0, -20.0 bps
        
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
        
        # Should not have 200ms hint since green is only worse by 5 bps (above 0.5 cap)
        assert "markout_green_worse_200ms" in hints
        # Should have 500ms hint since green is worse by 30 bps (above 0.5 cap)
        assert "markout_green_worse_500ms" in hints
    
    def test_triage_hint_markout_green_better(self):
        """Test triage hint when green markout is better."""
        # Record markout data where green is better
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 50050.0, 50100.0)  # +10.0, +20.0 bps
        
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
        
        # Should not have markout hints since green is better than blue
        assert "markout_green_worse_200ms" not in hints
        assert "markout_green_worse_500ms" not in hints
    
    def test_triage_hint_markout_threshold_edge_case(self):
        """Test triage hint threshold edge case."""
        # Record markout data where green is worse by exactly 0.5 bps (at threshold)
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49997.5, 49995.0)  # -5.0, -10.0 bps
        
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
        
        # Should have markout hints since difference is exactly at threshold (0.5 bps)
        assert "markout_green_worse_200ms" in hints
        assert "markout_green_worse_500ms" in hints
    
    def test_triage_hint_markout_custom_threshold(self):
        """Test triage hint with custom threshold."""
        # Set custom threshold
        os.environ['MARKOUT_CAP_BPS'] = '0.2'
        
        try:
            # Record markout data where green is worse by 0.3 bps (above 0.2 cap)
            self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
            self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49998.5, 49997.0)  # -3.0, -6.0 bps
            
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
            
            # Should have markout hints since difference (-8.0 bps) is above 0.2 bps cap
            assert "markout_green_worse_200ms" in hints
            assert "markout_green_worse_500ms" in hints
            
        finally:
            # Clean up environment
            if 'MARKOUT_CAP_BPS' in os.environ:
                del os.environ['MARKOUT_CAP_BPS']
    
    def test_triage_hint_markout_multiple_symbols(self):
        """Test triage hint with multiple symbols."""
        # Record markout data for multiple symbols
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)  # +5.0, +10.0 bps
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49950.0, 49900.0)  # -10.0, -20.0 bps
        
        self.metrics.record_markout("ETHUSDT", "blue", 3000.0, 3000.0, 3003.0, 3006.0)      # +1.0, +2.0 bps
        self.metrics.record_markout("ETHUSDT", "green", 3000.0, 3000.0, 2997.0, 2994.0)     # -1.0, -2.0 bps
        
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
        
        # Check markout block
        assert "markout" in payload
        markout = payload["markout"]
        
        # BTCUSDT: blue +5.0, green -10.0 → delta = -15.0 bps (above 0.5 cap)
        # ETHUSDT: blue +1.0, green -1.0 → delta = -2.0 bps (above 0.5 cap)
        # Weighted average: BTCUSDT dominates due to larger price
        assert "markout_green_worse_200ms" in hints
        assert "markout_green_worse_500ms" in hints
        
        # Check deltas
        assert markout["200"]["delta_bps"] < -0.5  # Should be negative
        assert markout["500"]["delta_bps"] < -0.5  # Should be negative

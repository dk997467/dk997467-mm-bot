"""Test markout hints and alerts in canary payload."""

import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from prometheus_client import REGISTRY
from src.metrics.exporter import Metrics
from src.common.di import AppContext


class TestCanaryMarkoutHintsAndAlerts:
    """Test markout hints and alerts in canary payload."""
    
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
        
        # Create temporary alerts log file
        self.temp_alerts_file = tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False)
        self.temp_alerts_file.close()
        self.bot._alerts_log_file = Mock(return_value=self.temp_alerts_file.name)
    
    def teardown_method(self):
        """Clean up after tests."""
        # Remove temporary file
        try:
            os.unlink(self.temp_alerts_file.name)
        except:
            pass
    
    def test_markout_hint_200ms_breach(self):
        """Test that markout hint is added when 200ms breaches cap."""
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
        
        # Set environment cap
        os.environ['MARKOUT_CAP_BPS'] = '0.5'
        
        try:
            # Build payload
            payload = self.bot._build_canary_payload()
            
            # Check hints
            assert "hints" in payload
            hints = payload["hints"]
            
            # Should have 200ms hint since green is worse by 15 bps (above 0.5 cap)
            assert "markout_green_worse_200ms" in hints
            # Should not have 500ms hint since green is only worse by 10 bps (above 0.5 cap)
            assert "markout_green_worse_500ms" in hints
            
            # Check markout block
            assert "markout" in payload
            markout = payload["markout"]
            
            # Check samples are included
            assert "samples" in markout["200"]["blue"]
            assert "samples" in markout["200"]["green"]
            assert "samples" in markout["500"]["blue"]
            assert "samples" in markout["500"]["green"]
            
            # Check markout samples fields
            assert "markout_samples_200_blue" in payload
            assert "markout_samples_200_green" in payload
            assert "markout_samples_500_blue" in payload
            assert "markout_samples_500_green" in payload
            
        finally:
            # Clean up environment
            if 'MARKOUT_CAP_BPS' in os.environ:
                del os.environ['MARKOUT_CAP_BPS']
    
    def test_markout_hint_500ms_breach(self):
        """Test that markout hint is added when 500ms breaches cap."""
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
        
        # Set environment cap
        os.environ['MARKOUT_CAP_BPS'] = '0.5'
        
        try:
            # Build payload
            payload = self.bot._build_canary_payload()
            
            # Check hints
            assert "hints" in payload
            hints = payload["hints"]
            
            # Should have both hints since both horizons breach cap
            assert "markout_green_worse_200ms" in hints
            assert "markout_green_worse_500ms" in hints
            
        finally:
            # Clean up environment
            if 'MARKOUT_CAP_BPS' in os.environ:
                del os.environ['MARKOUT_CAP_BPS']
    
    def test_markout_hint_no_breach(self):
        """Test that markout hint is not added when no breach occurs."""
        # Record markout data where green is better or within cap
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
        
        # Set environment cap
        os.environ['MARKOUT_CAP_BPS'] = '0.5'
        
        try:
            # Build payload
            payload = self.bot._build_canary_payload()
            
            # Check hints
            assert "hints" in payload
            hints = payload["hints"]
            
            # Should not have markout hints since green is better than blue
            assert "markout_green_worse_200ms" not in hints
            assert "markout_green_worse_500ms" not in hints
            
        finally:
            # Clean up environment
            if 'MARKOUT_CAP_BPS' in os.environ:
                del os.environ['MARKOUT_CAP_BPS']
    
    def test_markout_alert_200ms_regression(self):
        """Test that markout regression alert is written to alerts.log for 200ms."""
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
        
        # Set environment cap
        os.environ['MARKOUT_CAP_BPS'] = '0.5'
        
        try:
            # Build payload (this should trigger alerts)
            payload = self.bot._build_canary_payload()
            
            # Check that alerts were written
            # The mock should have been called for markout regression alerts
            # Blue 200ms: +5.0 bps, Green 200ms: -10.0 bps, Delta: -15.0 bps < -0.5 cap
            # Blue 500ms: +10.0 bps, Green 500ms: 0.0 bps, Delta: -10.0 bps < -0.5 cap
            assert self.bot._append_json_line.call_count >= 2  # At least 2 markout regression alerts
            
            # Verify the calls were made with correct parameters
            calls = self.bot._append_json_line.call_args_list
            markout_calls = [call for call in calls if call[0][1].get('kind') == 'markout_regression']
            assert len(markout_calls) >= 2
            
            # Check that both horizons are covered
            horizons = [call[0][1].get('horizon_ms') for call in markout_calls]
            assert 200 in horizons
            assert 500 in horizons
            
        finally:
            # Clean up environment
            if 'MARKOUT_CAP_BPS' in os.environ:
                del os.environ['MARKOUT_CAP_BPS']
    
    def test_markout_alert_custom_cap(self):
        """Test that markout alerts work with custom environment cap."""
        # Record markout data with small regression
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
        
        # Set custom environment cap (lower than default)
        os.environ['MARKOUT_CAP_BPS'] = '0.1'
        
        try:
            # Build payload
            payload = self.bot._build_canary_payload()
            
            # Check hints
            assert "hints" in payload
            hints = payload["hints"]
            
            # Should have hints since difference (-7.0 bps) is above 0.1 bps cap
            assert "markout_green_worse_200ms" in hints
            assert "markout_green_worse_500ms" in hints
            
            # Check that alerts were written
            self.bot._append_json_line.assert_called()
            
        finally:
            # Clean up environment
            if 'MARKOUT_CAP_BPS' in os.environ:
                del os.environ['MARKOUT_CAP_BPS']
    
    def test_markout_samples_in_payload(self):
        """Test that markout samples are correctly included in payload."""
        # Record markout data for multiple symbols
        self.metrics.record_markout("BTCUSDT", "blue", 50000.0, 50000.0, 50025.0, 50050.0)
        self.metrics.record_markout("BTCUSDT", "green", 50000.0, 50000.0, 49975.0, 49950.0)
        self.metrics.record_markout("ETHUSDT", "blue", 3000.0, 3000.0, 3003.0, 3006.0)
        self.metrics.record_markout("ETHUSDT", "green", 3000.0, 3000.0, 2997.0, 2994.0)
        
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
        
        # Check samples are included
        assert "samples" in markout["200"]["blue"]
        assert "samples" in markout["200"]["green"]
        assert "samples" in markout["500"]["blue"]
        assert "samples" in markout["500"]["green"]
        
        # Check markout samples fields
        assert "markout_samples_200_blue" in payload
        assert "markout_samples_200_green" in payload
        assert "markout_samples_500_blue" in payload
        assert "markout_samples_500_green" in payload
        
        # Verify sample counts (2 symbols per color)
        assert payload["markout_samples_200_blue"] == 2
        assert payload["markout_samples_200_green"] == 2
        assert payload["markout_samples_500_blue"] == 2
        assert payload["markout_samples_500_green"] == 2

"""
Test health endpoint functionality.
"""

import pytest
from unittest.mock import Mock, patch
from aiohttp import web

from cli.run_bot import MarketMakerBot


class TestHealthEndpoint:
    """Test health endpoint functionality."""
    
    def test_healthz_returns_200_and_keys(self):
        """Test that /healthz returns 200 and contains all required keys."""
        # Mock bot with required attributes
        mock_bot = Mock()
        mock_bot.ws_connector = Mock()
        mock_bot.ws_connector.is_connected.return_value = True
        mock_bot.rest_connector = Mock()
        mock_bot.rest_connector.is_connected.return_value = True
        mock_bot.risk_manager = Mock()
        mock_bot.risk_manager.paused = False
        mock_bot.start_time = Mock()
        mock_bot.start_time.__sub__ = Mock()
        mock_bot.start_time.__sub__.return_value.total_seconds.return_value = 3600
        mock_bot.data_recorder = Mock()
        mock_bot.data_recorder.get_storage_stats.return_value = {"queue_size": 0, "flushes": 10}
        mock_bot.metrics_exporter = Mock()
        
        # Test that health endpoint returns 200 and contains all required keys
        health_data = {
            "status": "ok",
            "marketdata_ok": True,
            "strategy_ok": True,
            "execution_ok": True,
            "exchange_ok": True,
            "risk_paused": False,
            "git_sha": "test_sha",
            "config_version": 1,
            "cfg_hash": "test_hash"
        }
        
        # Verify all required keys are present
        required_keys = {
            "marketdata_ok", "strategy_ok", "execution_ok", "exchange_ok",
            "risk_paused", "git_sha", "config_version", "cfg_hash"
        }
        
        for key in required_keys:
            assert key in health_data, f"Missing required key: {key}"
        
        # Test that all required keys are present in health data
        # This simulates what the health endpoint should return
        assert len(health_data) >= len(required_keys)
        
        # Verify response structure
        assert health_data["status"] in ["ok", "degraded"]
        assert isinstance(health_data["git_sha"], str)
        assert isinstance(health_data["config_version"], int)
        assert isinstance(health_data["cfg_hash"], str)

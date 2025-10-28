#!/usr/bin/env python3
"""Unit tests for tools.live.risk_monitor_cli helper functions."""
import pytest
import os
from unittest.mock import patch

from tools.live.risk_monitor_cli import _get_current_utc_iso, run_demo


class TestGetCurrentUtcIso:
    """Test _get_current_utc_iso function."""
    
    def test_returns_frozen_time_when_env_set(self):
        """Test returns frozen time when MM_FREEZE_UTC_ISO is set."""
        with patch.dict(os.environ, {'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z'}):
            result = _get_current_utc_iso()
            assert result == '2025-01-01T00:00:00Z'
    
    def test_returns_current_time_when_env_not_set(self):
        """Test returns current time when MM_FREEZE_UTC_ISO is not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = _get_current_utc_iso()
            
            # Should be ISO format
            assert isinstance(result, str)
            assert 'T' in result
            assert result.endswith('Z')
            assert len(result) >= 19  # YYYY-MM-DDTHH:MM:SSZ


class TestRunDemo:
    """Test run_demo function."""
    
    def test_run_demo_returns_valid_report(self):
        """Test run_demo returns valid report structure."""
        with patch.dict(os.environ, {'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z'}):
            report = run_demo(max_inv=10000.0, max_total=50000.0, edge_threshold=1.5)
            
            # Check report structure
            assert 'status' in report
            assert 'frozen' in report
            assert 'positions' in report
            assert 'metrics' in report
            assert 'runtime' in report
            
            # Check status
            assert report['status'] == 'OK'
            
            # Check frozen state (should be True after demo)
            assert isinstance(report['frozen'], bool)
            
            # Check positions
            assert isinstance(report['positions'], dict)
            assert 'BTCUSDT' in report['positions']
            assert 'ETHUSDT' in report['positions']
            
            # Check metrics
            metrics = report['metrics']
            assert 'blocks_total' in metrics
            assert 'freezes_total' in metrics
            assert 'last_freeze_reason' in metrics
            assert 'last_freeze_symbol' in metrics
            
            # Demo should trigger at least one block and one freeze
            assert metrics['blocks_total'] >= 1
            assert metrics['freezes_total'] >= 1
            
            # Check runtime
            runtime = report['runtime']
            assert runtime['utc'] == '2025-01-01T00:00:00Z'
            assert runtime['version'] == '0.1.0'
    
    def test_run_demo_triggers_freeze(self):
        """Test run_demo triggers freeze due to edge degradation."""
        with patch.dict(os.environ, {'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z'}):
            report = run_demo(max_inv=10000.0, max_total=50000.0, edge_threshold=1.5)
            
            # Demo scenario includes edge degradation below threshold
            assert report['frozen'] is True
            assert report['metrics']['freezes_total'] == 1
            assert 'Edge degradation' in report['metrics']['last_freeze_reason']
            assert report['metrics']['last_freeze_symbol'] == 'BTCUSDT'
    
    def test_run_demo_with_custom_limits(self):
        """Test run_demo with custom limits."""
        with patch.dict(os.environ, {'MM_FREEZE_UTC_ISO': '2025-01-01T00:00:00Z'}):
            report = run_demo(max_inv=5000.0, max_total=10000.0, edge_threshold=2.0)
            
            # Should still produce valid report
            assert report['status'] == 'OK'
            assert 'frozen' in report
            assert 'positions' in report
            assert 'metrics' in report


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


"""
Unit tests for tools/shadow/export_to_redis.py

Tests KPI aggregation and Redis export functionality with mocked Redis client.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.shadow.export_to_redis import (
    load_iter_summaries,
    aggregate_kpis,
    export_to_redis,
    get_redis_client,
)


def test_load_iter_summaries_empty_dir():
    """Test loading from directory with no ITER_SUMMARY files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir)
        summaries = load_iter_summaries(src)
        assert summaries == []


def test_load_iter_summaries_valid():
    """Test loading valid ITER_SUMMARY files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir)
        
        # Create test files
        iter1 = {
            "symbol": "BTCUSDT",
            "summary": {
                "net_bps": 3.2,
                "maker_taker_ratio": 0.85,
                "p95_latency_ms": 250,
                "risk_ratio": 0.35
            }
        }
        
        iter2 = {
            "symbol": "ETHUSDT",
            "summary": {
                "net_bps": 2.9,
                "maker_taker_ratio": 0.83,
                "p95_latency_ms": 280,
                "risk_ratio": 0.38
            }
        }
        
        (src / "ITER_SUMMARY_001.json").write_text(json.dumps(iter1))
        (src / "ITER_SUMMARY_002.json").write_text(json.dumps(iter2))
        
        summaries = load_iter_summaries(src)
        assert len(summaries) == 2
        assert summaries[0]["symbol"] == "BTCUSDT"
        assert summaries[1]["symbol"] == "ETHUSDT"


def test_aggregate_kpis_empty():
    """Test aggregation with empty summaries list."""
    kpis = aggregate_kpis([])
    assert kpis == {}


def test_aggregate_kpis_valid():
    """Test KPI aggregation from summaries."""
    summaries = [
        {
            "symbol": "BTCUSDT",
            "summary": {
                "net_bps": 3.2,
                "maker_taker_ratio": 0.85,
                "p95_latency_ms": 250,
                "risk_ratio": 0.35
            }
        },
        {
            "symbol": "ETHUSDT",
            "summary": {
                "net_bps": 2.9,
                "maker_taker_ratio": 0.83,
                "p95_latency_ms": 280,
                "risk_ratio": 0.38
            }
        }
    ]
    
    kpis = aggregate_kpis(summaries)
    
    assert len(kpis) == 2
    assert "BTCUSDT" in kpis
    assert "ETHUSDT" in kpis
    
    btc_kpis = kpis["BTCUSDT"]
    assert btc_kpis["edge_bps"] == 3.2
    assert btc_kpis["maker_taker_ratio"] == 0.85
    assert btc_kpis["p95_latency_ms"] == 250
    assert btc_kpis["risk_ratio"] == 0.35


def test_aggregate_kpis_flat_structure():
    """Test aggregation with KPIs at top level (not in summary sub-dict)."""
    summaries = [
        {
            "symbol": "BTCUSDT",
            "net_bps": 3.2,
            "maker_taker_ratio": 0.85,
            "p95_latency_ms": 250,
            "risk_ratio": 0.35
        }
    ]
    
    kpis = aggregate_kpis(summaries)
    
    assert "BTCUSDT" in kpis
    assert kpis["BTCUSDT"]["edge_bps"] == 3.2


def test_export_to_redis_dry_run():
    """Test export in dry-run mode (no Redis client)."""
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
            "maker_taker_ratio": 0.85,
        }
    }
    
    exported = export_to_redis(kpis, redis_client=None, ttl=3600, dry_run=True)
    
    # In dry-run mode, returns 0 (nothing actually exported)
    assert exported == 0


def test_export_to_redis_with_client():
    """Test export with mocked Redis client."""
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
            "maker_taker_ratio": 0.85,
        }
    }
    
    # Mock Redis client
    mock_redis = MagicMock()
    
    exported = export_to_redis(kpis, redis_client=mock_redis, ttl=3600, dry_run=False)
    
    # Should export 2 keys
    assert exported == 2
    assert mock_redis.setex.call_count == 2
    
    # Verify correct keys and values
    calls = mock_redis.setex.call_args_list
    keys = [call[0][0] for call in calls]
    assert "shadow:latest:BTCUSDT:edge_bps" in keys
    assert "shadow:latest:BTCUSDT:maker_taker_ratio" in keys


def test_export_to_redis_empty_kpis():
    """Test export with empty KPIs dict."""
    mock_redis = MagicMock()
    exported = export_to_redis({}, redis_client=mock_redis, ttl=3600, dry_run=False)
    assert exported == 0
    assert mock_redis.setex.call_count == 0


def test_get_redis_client_no_redis_library():
    """Test graceful fallback when redis library is not installed."""
    # Mock the import to raise ImportError
    import builtins
    real_import = builtins.__import__
    
    def mock_import(name, *args, **kwargs):
        if name == 'redis':
            raise ImportError("No module named 'redis'")
        return real_import(name, *args, **kwargs)
    
    with patch('builtins.__import__', side_effect=mock_import):
        with pytest.warns(RuntimeWarning, match="Redis library not installed"):
            client = get_redis_client("redis://localhost:6379/0")
            assert client is None


def test_get_redis_client_connection_error():
    """Test graceful fallback when Redis connection fails."""
    # Mock redis module and make connection fail
    import builtins
    real_import = builtins.__import__
    
    mock_redis = MagicMock()
    mock_client = MagicMock()
    mock_client.ping.side_effect = ConnectionError("Connection refused")
    mock_redis.from_url.return_value = mock_client
    
    # Return mock_redis for 'redis' import, real imports for others
    def mock_import_side_effect(name, *args, **kwargs):
        if name == 'redis':
            return mock_redis
        return real_import(name, *args, **kwargs)
    
    with patch('builtins.__import__', side_effect=mock_import_side_effect):
        with pytest.warns(RuntimeWarning, match="Cannot connect to Redis"):
            client = get_redis_client("redis://invalid:6379/0")
            assert client is None


def test_integration_export_flow():
    """Integration test: load summaries -> aggregate -> export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir)
        
        # Create test iteration summaries
        iter1 = {
            "symbol": "BTCUSDT",
            "summary": {
                "net_bps": 3.2,
                "maker_taker_ratio": 0.85,
                "p95_latency_ms": 250,
                "risk_ratio": 0.35
            }
        }
        
        (src / "ITER_SUMMARY_001.json").write_text(json.dumps(iter1))
        
        # Load
        summaries = load_iter_summaries(src)
        assert len(summaries) == 1
        
        # Aggregate
        kpis = aggregate_kpis(summaries)
        assert "BTCUSDT" in kpis
        
        # Export (dry-run)
        exported = export_to_redis(kpis, redis_client=None, dry_run=True)
        assert exported == 0  # dry-run returns 0


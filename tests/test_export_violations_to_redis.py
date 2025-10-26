"""Tests for tools/soak/export_violations_to_redis.py"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from tools.soak.export_violations_to_redis import (
    get_redis_client,
    export_violations_hash,
    export_violations_stream
)


@pytest.fixture
def sample_summary():
    """Sample SOAK_SUMMARY.json"""
    return {
        "generated_at_utc": "2025-10-21T12:34:56Z",
        "windows": 24,
        "min_windows_required": 24,
        "symbols": {
            "BTCUSDT": {
                "edge_bps": {"median": 3.2, "last": 3.1, "trend": "↑", "status": "OK"},
                "maker_taker_ratio": {"median": 0.84, "last": 0.86, "trend": "≈", "status": "OK"},
                "p95_latency_ms": {"median": 245, "last": 232, "trend": "↓", "status": "OK"},
                "risk_ratio": {"median": 0.33, "last": 0.34, "trend": "≈", "status": "OK"}
            },
            "ETHUSDT": {
                "edge_bps": {"median": 2.9, "last": 2.45, "trend": "↓", "status": "WARN"},
                "maker_taker_ratio": {"median": 0.78, "last": 0.78, "trend": "≈", "status": "WARN"},
                "p95_latency_ms": {"median": 340, "last": 360, "trend": "↑", "status": "WARN"},
                "risk_ratio": {"median": 0.41, "last": 0.42, "trend": "↑", "status": "WARN"}
            }
        },
        "overall": {
            "crit_count": 0,
            "warn_count": 4,
            "ok_count": 1,
            "verdict": "WARN"
        },
        "meta": {
            "commit_range": "abc123..def456",
            "profile": "moderate",
            "source": "soak"
        }
    }


@pytest.fixture
def sample_violations():
    """Sample VIOLATIONS.json"""
    return [
        {
            "symbol": "ETHUSDT",
            "metric": "edge_bps",
            "level": "WARN",
            "window_index": 22,
            "value": 2.45,
            "threshold": 2.5,
            "note": "Edge below warning threshold"
        },
        {
            "symbol": "ETHUSDT",
            "metric": "maker_taker_ratio",
            "level": "WARN",
            "window_index": 23,
            "value": 0.78,
            "threshold": 0.80,
            "note": "Low maker ratio"
        },
        {
            "symbol": "ETHUSDT",
            "metric": "p95_latency_ms",
            "level": "WARN",
            "window_index": 21,
            "value": 360,
            "threshold": 350,
            "note": "High latency"
        },
        {
            "symbol": "ETHUSDT",
            "metric": "risk_ratio",
            "level": "WARN",
            "window_index": 20,
            "value": 0.42,
            "threshold": 0.40,
            "note": "Elevated risk"
        }
    ]


def test_get_redis_client_no_library():
    """Test graceful fallback when redis library not available."""
    with patch("builtins.__import__", side_effect=ImportError("No module named 'redis'")):
        client = get_redis_client("redis://localhost:6379/0")
        assert client is None


def test_get_redis_client_connection_error():
    """Test graceful fallback when Redis connection fails."""
    mock_redis = MagicMock()
    mock_redis.from_url.side_effect = Exception("Connection refused")
    
    with patch("builtins.__import__", return_value=mock_redis):
        client = get_redis_client("redis://localhost:6379/0")
        assert client is None


def test_export_violations_hash(sample_summary, sample_violations):
    """Test export_violations_hash with mock Redis client."""
    # Mock Redis client
    mock_client = MagicMock()
    mock_pipe = MagicMock()
    mock_client.pipeline.return_value = mock_pipe
    mock_pipe.execute.return_value = [True, True]
    
    # Export
    exported = export_violations_hash(
        mock_client,
        sample_summary,
        sample_violations,
        env="dev",
        exchange="bybit",
        ttl=3600
    )
    
    # Should export 2 symbols
    assert exported == 2
    
    # Verify pipeline was called
    assert mock_client.pipeline.call_count == 2
    
    # Verify HSET was called with correct keys
    calls = mock_pipe.hset.call_args_list
    assert len(calls) == 2
    
    # First call should be for BTCUSDT (OK)
    btc_hash_key = "dev:bybit:soak:violations:BTCUSDT"
    btc_data = calls[0][0][0]
    assert btc_data == btc_hash_key or btc_data == "dev:bybit:soak:violations:ETHUSDT"
    
    # Check data structure
    for call in calls:
        hash_data = call[1]["mapping"]
        assert "crit_count" in hash_data
        assert "warn_count" in hash_data
        assert "last_edge" in hash_data
        assert "last_maker_taker" in hash_data
        assert "last_latency_p95" in hash_data
        assert "last_risk" in hash_data
        assert "verdict" in hash_data
        assert "updated_at" in hash_data
    
    # Verify EXPIRE was called
    assert mock_pipe.expire.call_count == 2


def test_export_violations_hash_counts(sample_summary, sample_violations):
    """Test correct counting of violations."""
    mock_client = MagicMock()
    mock_pipe = MagicMock()
    mock_client.pipeline.return_value = mock_pipe
    mock_pipe.execute.return_value = [True, True]
    
    export_violations_hash(
        mock_client,
        sample_summary,
        sample_violations,
        env="dev",
        exchange="bybit",
        ttl=3600
    )
    
    calls = mock_pipe.hset.call_args_list
    
    # Find ETHUSDT hash (should have 4 warnings)
    for call in calls:
        hash_data = call[1]["mapping"]
        if hash_data.get("warn_count") == 4:
            assert hash_data["crit_count"] == 0
            assert hash_data["verdict"] == "WARN"
            break
    else:
        pytest.fail("ETHUSDT with 4 warnings not found")


def test_export_violations_stream(sample_violations):
    """Test export_violations_stream with mock Redis client."""
    mock_client = MagicMock()
    mock_client.xadd.return_value = "1234567890-0"
    
    # Export
    exported = export_violations_stream(
        mock_client,
        sample_violations,
        env="dev",
        exchange="bybit"
    )
    
    # Should export 4 events
    assert exported == 4
    
    # Verify XADD was called 4 times
    assert mock_client.xadd.call_count == 4
    
    # Verify stream keys
    for call in mock_client.xadd.call_args_list:
        stream_key = call[0][0]
        entry = call[0][1]
        
        # Check key format
        assert stream_key.startswith("dev:bybit:soak:violations:stream:")
        assert "ETHUSDT" in stream_key
        
        # Check entry structure
        assert "metric" in entry
        assert "level" in entry
        assert "value" in entry
        assert "threshold" in entry
        assert "window_index" in entry
        assert "note" in entry
        assert "ts" in entry
        
        # maxlen should be set
        assert call[1]["maxlen"] == 1000


def test_export_violations_hash_with_crit():
    """Test verdict determination with CRIT violations."""
    summary = {
        "symbols": {
            "BTCUSDT": {
                "edge_bps": {"last": 1.8},
                "maker_taker_ratio": {"last": 0.65},
                "p95_latency_ms": {"last": 420},
                "risk_ratio": {"last": 0.55}
            }
        }
    }
    
    violations = [
        {"symbol": "BTCUSDT", "level": "CRIT", "metric": "edge_bps"},
        {"symbol": "BTCUSDT", "level": "CRIT", "metric": "maker_taker_ratio"},
        {"symbol": "BTCUSDT", "level": "WARN", "metric": "p95_latency_ms"}
    ]
    
    mock_client = MagicMock()
    mock_pipe = MagicMock()
    mock_client.pipeline.return_value = mock_pipe
    mock_pipe.execute.return_value = [True, True]
    
    export_violations_hash(
        mock_client,
        summary,
        violations,
        env="prod",
        exchange="bybit",
        ttl=7200
    )
    
    # Check hash data
    hash_data = mock_pipe.hset.call_args[1]["mapping"]
    assert hash_data["crit_count"] == 2
    assert hash_data["warn_count"] == 1
    assert hash_data["verdict"] == "CRIT"


def test_export_with_files(tmp_path, sample_summary, sample_violations):
    """Test main() flow with actual files."""
    from tools.soak.export_violations_to_redis import main
    
    # Create temporary files
    summary_file = tmp_path / "SOAK_SUMMARY.json"
    violations_file = tmp_path / "VIOLATIONS.json"
    
    summary_file.write_text(json.dumps(sample_summary), encoding="utf-8")
    violations_file.write_text(json.dumps(sample_violations), encoding="utf-8")
    
    # Mock Redis client
    mock_client = MagicMock()
    mock_pipe = MagicMock()
    mock_client.pipeline.return_value = mock_pipe
    mock_pipe.execute.return_value = [True, True]
    
    with patch("tools.soak.export_violations_to_redis.get_redis_client", return_value=mock_client):
        with patch("sys.argv", [
            "export_violations_to_redis.py",
            "--summary", str(summary_file),
            "--violations", str(violations_file),
            "--env", "dev",
            "--exchange", "bybit",
            "--redis-url", "redis://localhost:6379/0"
        ]):
            exit_code = main()
    
    assert exit_code == 0
    assert mock_pipe.hset.call_count == 2


def test_export_with_stream_flag(tmp_path, sample_summary, sample_violations):
    """Test main() with --stream flag."""
    from tools.soak.export_violations_to_redis import main
    
    # Create temporary files
    summary_file = tmp_path / "SOAK_SUMMARY.json"
    violations_file = tmp_path / "VIOLATIONS.json"
    
    summary_file.write_text(json.dumps(sample_summary), encoding="utf-8")
    violations_file.write_text(json.dumps(sample_violations), encoding="utf-8")
    
    # Mock Redis client
    mock_client = MagicMock()
    mock_pipe = MagicMock()
    mock_client.pipeline.return_value = mock_pipe
    mock_pipe.execute.return_value = [True, True]
    mock_client.xadd.return_value = "1234567890-0"
    
    with patch("tools.soak.export_violations_to_redis.get_redis_client", return_value=mock_client):
        with patch("sys.argv", [
            "export_violations_to_redis.py",
            "--summary", str(summary_file),
            "--violations", str(violations_file),
            "--env", "dev",
            "--exchange", "bybit",
            "--redis-url", "redis://localhost:6379/0",
            "--stream"
        ]):
            exit_code = main()
    
    assert exit_code == 0
    assert mock_pipe.hset.call_count == 2
    assert mock_client.xadd.call_count == 4  # 4 violations


def test_export_missing_files(tmp_path):
    """Test graceful error when files don't exist."""
    from tools.soak.export_violations_to_redis import main
    
    with patch("sys.argv", [
        "export_violations_to_redis.py",
        "--summary", str(tmp_path / "missing.json"),
        "--violations", str(tmp_path / "missing2.json")
    ]):
        exit_code = main()
    
    assert exit_code == 1


def test_export_redis_unavailable(tmp_path, sample_summary, sample_violations):
    """Test graceful fallback when Redis is unavailable."""
    from tools.soak.export_violations_to_redis import main
    
    # Create temporary files
    summary_file = tmp_path / "SOAK_SUMMARY.json"
    violations_file = tmp_path / "VIOLATIONS.json"
    
    summary_file.write_text(json.dumps(sample_summary), encoding="utf-8")
    violations_file.write_text(json.dumps(sample_violations), encoding="utf-8")
    
    # Mock Redis client returns None (unavailable)
    with patch("tools.soak.export_violations_to_redis.get_redis_client", return_value=None):
        with patch("sys.argv", [
            "export_violations_to_redis.py",
            "--summary", str(summary_file),
            "--violations", str(violations_file)
        ]):
            exit_code = main()
    
    # Should exit 0 (graceful fallback)
    assert exit_code == 0


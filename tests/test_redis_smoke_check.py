"""
Unit tests for tools/shadow/redis_smoke_check.py

Tests smoke check functionality with mocked Redis client.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.shadow.redis_smoke_check import (
    get_redis_client,
    scan_keys,
    verify_hash_keys,
    verify_flat_backfill,
    generate_report
)


def test_get_redis_client_success():
    """Test successful Redis client creation."""
    # Mock redis library import
    import builtins
    real_import = builtins.__import__
    
    def mock_import(name, *args, **kwargs):
        if name == "redis":
            mock_redis = MagicMock()
            mock_client = MagicMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.ping.return_value = True
            return mock_redis
        return real_import(name, *args, **kwargs)
    
    with patch("builtins.__import__", side_effect=mock_import):
        client = get_redis_client("redis://localhost:6379/0")
        assert client is not None


def test_get_redis_client_connection_failure():
    """Test Redis client creation with connection failure."""
    import builtins
    real_import = builtins.__import__
    
    def mock_import(name, *args, **kwargs):
        if name == "redis":
            mock_redis = MagicMock()
            mock_client = MagicMock()
            mock_redis.from_url.return_value = mock_client
            mock_client.ping.side_effect = Exception("Connection refused")
            return mock_redis
        return real_import(name, *args, **kwargs)
    
    with patch("builtins.__import__", side_effect=mock_import):
        client = get_redis_client("redis://localhost:6379/0")
        assert client is None


def test_get_redis_client_no_library():
    """Test Redis client when redis library not installed."""
    import builtins
    real_import = builtins.__import__
    
    def mock_import(name, *args, **kwargs):
        if name == "redis":
            raise ImportError("No module named 'redis'")
        return real_import(name, *args, **kwargs)
    
    with patch("builtins.__import__", side_effect=mock_import):
        client = get_redis_client("redis://localhost:6379/0")
        assert client is None


def test_scan_keys():
    """Test Redis key scanning."""
    mock_client = MagicMock()
    
    # Mock scan to return keys in batches
    mock_client.scan.side_effect = [
        (10, ["key1", "key2", "key3"]),  # First batch
        (0, ["key4", "key5"])             # Final batch (cursor=0)
    ]
    
    keys = scan_keys(mock_client, "dev:bybit:*", limit=1000)
    
    assert len(keys) == 5
    assert "key1" in keys
    assert "key5" in keys


def test_scan_keys_with_limit():
    """Test key scanning respects limit."""
    mock_client = MagicMock()
    
    # Return many keys
    mock_client.scan.side_effect = [
        (10, [f"key{i}" for i in range(100)]),
        (0, [f"key{i}" for i in range(100, 200)])
    ]
    
    keys = scan_keys(mock_client, "dev:bybit:*", limit=50)
    
    # Should stop at limit
    assert len(keys) == 50


def test_verify_hash_keys_all_pass():
    """Test hash key verification when all keys pass."""
    mock_client = MagicMock()
    
    # Mock TTL and HGETALL responses
    mock_client.ttl.return_value = 3600  # Valid TTL
    mock_client.hgetall.return_value = {
        "edge_bps": "3.2",
        "maker_taker_ratio": "0.85",
        "p95_latency_ms": "250",
        "risk_ratio": "0.35"
    }
    
    keys = [f"dev:bybit:shadow:latest:SYM{i:02d}" for i in range(10)]
    results = verify_hash_keys(mock_client, keys, sample_size=10)
    
    assert results["status"] == "PASS"
    assert results["passed"] == 10
    assert results["failed"] == 0
    assert results["total_keys"] == 10


def test_verify_hash_keys_with_issues():
    """Test hash key verification with issues."""
    mock_client = MagicMock()
    
    # First key: invalid TTL
    # Second key: missing fields
    # Third key: valid
    mock_client.ttl.side_effect = [-1, 3600, 3600]
    mock_client.hgetall.side_effect = [
        {"edge_bps": "3.2", "maker_taker_ratio": "0.85", "p95_latency_ms": "250", "risk_ratio": "0.35"},
        {"edge_bps": "3.2"},  # Missing fields
        {"edge_bps": "3.2", "maker_taker_ratio": "0.85", "p95_latency_ms": "250", "risk_ratio": "0.35"}
    ]
    
    keys = ["key1", "key2", "key3"]
    results = verify_hash_keys(mock_client, keys, sample_size=3)
    
    assert results["status"] == "FAIL"
    assert results["passed"] == 1
    assert results["failed"] == 2
    assert len(results["issues"]) > 0


def test_verify_hash_keys_empty():
    """Test hash key verification with no keys."""
    mock_client = MagicMock()
    
    results = verify_hash_keys(mock_client, [], sample_size=10)
    
    assert results["status"] == "FAIL"
    assert "No keys found" in results["reason"]


def test_verify_flat_backfill_all_match():
    """Test flat backfill verification with matching values."""
    mock_client = MagicMock()
    
    # Mock hash data
    mock_client.hgetall.return_value = {
        "edge_bps": "3.2",
        "maker_taker_ratio": "0.85",
        "p95_latency_ms": "250",
        "risk_ratio": "0.35"
    }
    
    # Mock flat data (same values)
    mock_client.get.side_effect = ["3.2", "0.85", "250", "0.35"]
    
    hash_keys = ["dev:bybit:shadow:latest:BTCUSDT"]
    results = verify_flat_backfill(
        mock_client,
        "dev",
        "bybit",
        hash_keys,
        "dev:bybit:shadow:latest:flat",
        sample_size=1
    )
    
    assert results["status"] == "PASS"
    assert results["matches"] == 1
    assert results["mismatches"] == 0


def test_verify_flat_backfill_with_mismatches():
    """Test flat backfill verification with mismatches."""
    mock_client = MagicMock()
    
    # Mock hash data
    mock_client.hgetall.return_value = {
        "edge_bps": "3.2",
        "maker_taker_ratio": "0.85",
        "p95_latency_ms": "250",
        "risk_ratio": "0.35"
    }
    
    # Mock flat data (different values)
    mock_client.get.side_effect = ["3.5", "0.85", "250", "0.35"]  # edge_bps mismatch
    
    hash_keys = ["dev:bybit:shadow:latest:BTCUSDT"]
    results = verify_flat_backfill(
        mock_client,
        "dev",
        "bybit",
        hash_keys,
        "dev:bybit:shadow:latest:flat",
        sample_size=1
    )
    
    assert results["status"] == "WARN"
    assert results["mismatches"] == 1


def test_verify_flat_backfill_missing_flat():
    """Test flat backfill verification with missing flat keys."""
    mock_client = MagicMock()
    
    # Mock hash data
    mock_client.hgetall.return_value = {
        "edge_bps": "3.2",
        "maker_taker_ratio": "0.85",
        "p95_latency_ms": "250",
        "risk_ratio": "0.35"
    }
    
    # Mock flat data (all None - not found)
    mock_client.get.return_value = None
    
    hash_keys = ["dev:bybit:shadow:latest:BTCUSDT"]
    results = verify_flat_backfill(
        mock_client,
        "dev",
        "bybit",
        hash_keys,
        "dev:bybit:shadow:latest:flat",
        sample_size=1
    )
    
    assert results["status"] == "WARN"
    assert results["missing_flat"] == 1


def test_generate_report_pass():
    """Test report generation with PASS verdict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "REDIS_SMOKE_REPORT.md"
        
        export_results = {
            "exported_count": 10,
            "wall_time_ms": 142.35,
            "batch_size": 100,
            "mode": "hash",
            "metrics": {
                "redis_export_success_total": 10,
                "redis_export_fail_total": 0,
                "redis_export_batches_total": 1,
                "redis_export_keys_written_total": 40,
                "redis_export_batch_duration_ms": 15.2
            }
        }
        
        hash_verification = {
            "status": "PASS",
            "total_keys": 10,
            "sampled": 10,
            "passed": 10,
            "failed": 0,
            "sample_details": [
                {
                    "key": "dev:bybit:shadow:latest:BTCUSDT",
                    "ttl": 3600,
                    "fields": ["edge_bps", "maker_taker_ratio", "p95_latency_ms", "risk_ratio"],
                    "values": {"edge_bps": "3.2"},
                    "issues": []
                }
            ]
        }
        
        verdict = generate_report(output_path, export_results, hash_verification)
        
        assert verdict == "PASS"
        assert output_path.exists()
        
        content = output_path.read_text()
        assert "**Verdict:** PASS" in content
        assert "142.35ms" in content
        assert "Exported Count:** 10" in content


def test_generate_report_fail():
    """Test report generation with FAIL verdict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "REDIS_SMOKE_REPORT.md"
        
        export_results = {
            "exported_count": 0,  # No keys exported
            "wall_time_ms": 0.0,
            "batch_size": 100,
            "mode": "hash",
            "metrics": {}
        }
        
        hash_verification = {
            "status": "FAIL",
            "reason": "No keys found"
        }
        
        verdict = generate_report(output_path, export_results, hash_verification)
        
        assert verdict == "FAIL"
        assert output_path.exists()
        
        content = output_path.read_text()
        assert "**Verdict:** FAIL" in content
        assert "No keys exported" in content


def test_generate_report_with_flat_verification():
    """Test report generation with flat mode verification."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "REDIS_SMOKE_REPORT.md"
        
        export_results = {
            "exported_count": 5,
            "wall_time_ms": 100.0,
            "batch_size": 50,
            "mode": "hash",
            "metrics": {}
        }
        
        hash_verification = {
            "status": "PASS",
            "total_keys": 5,
            "sampled": 5,
            "passed": 5,
            "failed": 0,
            "sample_details": []
        }
        
        flat_verification = {
            "status": "WARN",
            "symbols_checked": 5,
            "matches": 4,
            "mismatches": 1,
            "missing_flat": 0,
            "details": [
                {
                    "symbol": "BTCUSDT",
                    "status": "MATCH",
                    "hash_data": {"edge_bps": "3.2"},
                    "flat_data": {"edge_bps": "3.2"}
                }
            ]
        }
        
        verdict = generate_report(
            output_path,
            export_results,
            hash_verification,
            flat_verification
        )
        
        assert verdict == "WARN"
        assert output_path.exists()
        
        content = output_path.read_text()
        assert "Flat Mode Cross-Verification" in content
        assert "Mismatches:** 1" in content


def test_report_includes_key_samples():
    """Test that report includes sample key details."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "REDIS_SMOKE_REPORT.md"
        
        export_results = {
            "exported_count": 3,
            "wall_time_ms": 50.0,
            "batch_size": 10,
            "mode": "hash",
            "metrics": {}
        }
        
        hash_verification = {
            "status": "PASS",
            "total_keys": 3,
            "sampled": 3,
            "passed": 3,
            "failed": 0,
            "sample_details": [
                {
                    "key": "dev:bybit:shadow:latest:BTCUSDT",
                    "ttl": 3600,
                    "fields": ["edge_bps", "maker_taker_ratio", "p95_latency_ms", "risk_ratio"],
                    "values": {},
                    "issues": []
                },
                {
                    "key": "dev:bybit:shadow:latest:ETHUSDT",
                    "ttl": 3500,
                    "fields": ["edge_bps", "maker_taker_ratio", "p95_latency_ms", "risk_ratio"],
                    "values": {},
                    "issues": []
                }
            ]
        }
        
        generate_report(output_path, export_results, hash_verification)
        
        content = output_path.read_text()
        assert "Sample Key Details" in content
        assert "| BTCUSDT | 3600s |" in content
        assert "| ETHUSDT | 3500s |" in content


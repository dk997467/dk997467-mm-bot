"""
Unit tests for tools/shadow/export_to_redis.py

Tests KPI aggregation and Redis export functionality with mocked Redis client.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.shadow.export_to_redis import (
    load_iter_summaries,
    aggregate_kpis,
    export_to_redis,
    get_redis_client,
    normalize_symbol,
    build_redis_key,
    METRICS,
    reset_metrics,
    print_metrics,
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
    
    # In dry-run mode with hash mode (default), returns 1 symbol
    assert exported == 1


def test_export_to_redis_with_client():
    """Test export with mocked Redis client."""
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
            "maker_taker_ratio": 0.85,
        }
    }
    
    # Mock Redis client and pipeline
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute.return_value = [2, 1]  # HSET returns 2, EXPIRE returns 1
    
    # Test with default env/exchange (dev/bybit) in hash mode (default)
    exported = export_to_redis(kpis, redis_client=mock_redis, ttl=3600, dry_run=False)
    
    # Should export 1 symbol in hash mode
    assert exported == 1
    assert mock_pipeline.hset.call_count == 1
    assert mock_pipeline.expire.call_count == 1
    
    # Verify correct hash key (with default namespace)
    call_args = mock_pipeline.hset.call_args
    assert "dev:bybit:shadow:latest:BTCUSDT" in str(call_args)


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


def test_normalize_symbol():
    """Test symbol normalization to A-Z0-9."""
    assert normalize_symbol("BTCUSDT") == "BTCUSDT"
    assert normalize_symbol("BTC-USDT") == "BTCUSDT"
    assert normalize_symbol("btc/usdt") == "BTCUSDT"
    assert normalize_symbol("BTC_USDT") == "BTCUSDT"
    assert normalize_symbol("btc.usdt") == "BTCUSDT"
    assert normalize_symbol("BTC:USDT") == "BTCUSDT"
    # Mixed case and special chars
    assert normalize_symbol("btC-UsD/t") == "BTCUSDT"
    # Numbers
    assert normalize_symbol("ETH2USDT") == "ETH2USDT"


def test_build_redis_key():
    """Test namespaced Redis key building."""
    # Standard case
    key = build_redis_key("dev", "bybit", "BTCUSDT", "edge_bps")
    assert key == "dev:bybit:shadow:latest:BTCUSDT:edge_bps"
    
    # Production environment
    key = build_redis_key("prod", "binance", "ETHUSDT", "maker_taker_ratio")
    assert key == "prod:binance:shadow:latest:ETHUSDT:maker_taker_ratio"
    
    # Symbol with special chars gets normalized
    key = build_redis_key("staging", "bybit", "BTC-USDT", "risk_ratio")
    assert key == "staging:bybit:shadow:latest:BTCUSDT:risk_ratio"
    
    # Lowercase symbol gets uppercase
    key = build_redis_key("dev", "bybit", "btcusdt", "p95_latency_ms")
    assert key == "dev:bybit:shadow:latest:BTCUSDT:p95_latency_ms"


def test_export_to_redis_with_namespacing():
    """Test export with env and exchange namespacing."""
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
            "maker_taker_ratio": 0.85,
        }
    }
    
    # Mock Redis client and pipeline
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute.return_value = [2, 1]  # HSET returns 2, EXPIRE returns 1
    
    exported = export_to_redis(
        kpis,
        redis_client=mock_redis,
        env="prod",
        exchange="binance",
        ttl=7200,
        dry_run=False
    )
    
    # Should export 1 symbol in hash mode
    assert exported == 1
    assert mock_pipeline.hset.call_count == 1
    assert mock_pipeline.expire.call_count == 1
    
    # Verify namespaced hash key
    call_args = mock_pipeline.hset.call_args
    assert "prod:binance:shadow:latest:BTCUSDT" in str(call_args)


def test_get_redis_client_with_auth():
    """Test Redis client creation with authentication URL."""
    # Test that URL with auth is properly parsed (we can't test actual connection)
    # This test just ensures the function handles auth URLs without crashing
    import builtins
    real_import = builtins.__import__
    
    mock_redis = MagicMock()
    mock_client = MagicMock()
    mock_client.ping.return_value = True
    mock_redis.from_url.return_value = mock_client
    
    def mock_import(name, *args, **kwargs):
        if name == 'redis':
            return mock_redis
        return real_import(name, *args, **kwargs)
    
    with patch('builtins.__import__', side_effect=mock_import):
        client = get_redis_client("redis://user:pass@localhost:6379/0")
        assert client is not None
        
        # Verify from_url was called with auth URL
        mock_redis.from_url.assert_called_once()
        call_args = mock_redis.from_url.call_args
        assert "user:pass" in call_args[0][0]


def test_get_redis_client_with_tls():
    """Test Redis client creation with rediss:// (TLS) URL."""
    import builtins
    real_import = builtins.__import__
    
    mock_redis = MagicMock()
    mock_client = MagicMock()
    mock_client.ping.return_value = True
    mock_redis.from_url.return_value = mock_client
    
    def mock_import(name, *args, **kwargs):
        if name == 'redis':
            return mock_redis
        return real_import(name, *args, **kwargs)
    
    with patch('builtins.__import__', side_effect=mock_import):
        client = get_redis_client("rediss://prod.redis.com:6380/0")
        assert client is not None
        
        # Verify from_url was called with rediss:// URL
        mock_redis.from_url.assert_called_once()
        call_args = mock_redis.from_url.call_args
        assert "rediss://" in call_args[0][0]


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
        assert exported >= 1  # dry-run now returns count of exported items


# ==============================================================================
# NEW TESTS: Hash Mode, Flat Mode, Batching, Metrics
# ==============================================================================


def test_export_hash_mode_dry_run():
    """Test export in hash mode (dry-run)."""
    reset_metrics()
    
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
            "maker_taker_ratio": 0.85,
            "p95_latency_ms": 250,
            "risk_ratio": 0.35
        },
        "ETHUSDT": {
            "edge_bps": 2.9,
            "maker_taker_ratio": 0.83,
            "p95_latency_ms": 280,
            "risk_ratio": 0.38
        }
    }
    
    # Export in hash mode (dry-run)
    exported = export_to_redis(
        kpis,
        redis_client=None,
        env="dev",
        exchange="bybit",
        ttl=3600,
        dry_run=True,
        hash_mode=True,
        batch_size=10
    )
    
    # Should export 2 symbols
    assert exported == 2
    
    # Metrics should show correct counts (with labels)
    labels = ("dev", "bybit", "hash")
    assert METRICS["redis_export_keys_written_total"][labels] == 8  # 2 symbols × 4 KPIs
    assert METRICS["redis_export_mode"][("dev", "bybit")] == "hash"


def test_export_flat_mode_dry_run():
    """Test export in flat mode (dry-run)."""
    reset_metrics()
    
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
            "maker_taker_ratio": 0.85,
        }
    }
    
    # Export in flat mode (dry-run)
    exported = export_to_redis(
        kpis,
        redis_client=None,
        env="dev",
        exchange="bybit",
        ttl=3600,
        dry_run=True,
        hash_mode=False,
        batch_size=10
    )
    
    # Should export 2 keys
    assert exported == 2
    
    # Metrics should show correct counts (with labels)
    labels = ("dev", "bybit", "flat")
    assert METRICS["redis_export_keys_written_total"][labels] == 2
    assert METRICS["redis_export_mode"][("dev", "bybit")] == "flat"


def test_export_hash_mode_with_mock_redis():
    """Test export in hash mode with mocked Redis client."""
    reset_metrics()
    
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
            "maker_taker_ratio": 0.85,
            "p95_latency_ms": 250,
            "risk_ratio": 0.35
        }
    }
    
    # Mock Redis client and pipeline
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    
    # Mock pipeline execution results: HSET returns 4 (fields added), EXPIRE returns 1
    mock_pipeline.execute.return_value = [4, 1]
    
    # Export in hash mode
    exported = export_to_redis(
        kpis,
        redis_client=mock_redis,
        env="dev",
        exchange="bybit",
        ttl=3600,
        dry_run=False,
        hash_mode=True,
        batch_size=10
    )
    
    # Verify pipeline was used
    assert mock_redis.pipeline.called
    assert mock_pipeline.hset.called
    assert mock_pipeline.expire.called
    assert mock_pipeline.execute.called
    
    # Verify HSET was called with correct arguments
    call_args = mock_pipeline.hset.call_args
    assert "dev:bybit:shadow:latest:BTCUSDT" in str(call_args)
    
    # Should export 1 symbol
    assert exported == 1
    
    # Metrics should be updated (with labels)
    labels = ("dev", "bybit", "hash")
    assert METRICS["redis_export_batches_total"][labels] == 1
    assert METRICS["redis_export_keys_written_total"][labels] == 4


def test_export_flat_mode_with_mock_redis():
    """Test export in flat mode with mocked Redis client."""
    reset_metrics()
    
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
            "maker_taker_ratio": 0.85,
        }
    }
    
    # Mock Redis client and pipeline
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    
    # Mock pipeline execution results: SETEX returns True
    mock_pipeline.execute.return_value = [True, True]
    
    # Export in flat mode
    exported = export_to_redis(
        kpis,
        redis_client=mock_redis,
        env="dev",
        exchange="bybit",
        ttl=3600,
        dry_run=False,
        hash_mode=False,
        batch_size=10
    )
    
    # Verify pipeline was used
    assert mock_redis.pipeline.called
    assert mock_pipeline.setex.called
    assert mock_pipeline.execute.called
    
    # Verify SETEX was called twice (2 KPIs)
    assert mock_pipeline.setex.call_count == 2
    
    # Should export 2 keys
    assert exported == 2
    
    # Metrics should be updated (with labels)
    labels = ("dev", "bybit", "flat")
    assert METRICS["redis_export_batches_total"][labels] == 1
    assert METRICS["redis_export_keys_written_total"][labels] == 2


def test_export_batching():
    """Test that export properly splits into batches."""
    reset_metrics()
    
    # Create 15 symbols (with batch_size=5, should create 3 batches)
    kpis = {}
    for i in range(15):
        kpis[f"SYM{i:02d}"] = {
            "edge_bps": 3.0 + i * 0.1,
            "maker_taker_ratio": 0.8 + i * 0.01,
        }
    
    # Mock Redis client and pipeline
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    
    # Mock successful HSET + EXPIRE for each symbol (2 results per symbol)
    # Batch 1: 5 symbols = 10 results (5 HSET + 5 EXPIRE)
    # Batch 2: 5 symbols = 10 results
    # Batch 3: 5 symbols = 10 results
    mock_pipeline.execute.side_effect = [
        [2, 1, 2, 1, 2, 1, 2, 1, 2, 1],  # Batch 1
        [2, 1, 2, 1, 2, 1, 2, 1, 2, 1],  # Batch 2
        [2, 1, 2, 1, 2, 1, 2, 1, 2, 1],  # Batch 3
    ]
    
    # Export in hash mode with batch_size=5
    exported = export_to_redis(
        kpis,
        redis_client=mock_redis,
        env="dev",
        exchange="bybit",
        ttl=3600,
        dry_run=False,
        hash_mode=True,
        batch_size=5
    )
    
    # Should export all 15 symbols
    assert exported == 15
    
    # Should create 3 batches (15 symbols / batch_size 5) (with labels)
    labels = ("dev", "bybit", "hash")
    assert METRICS["redis_export_batches_total"][labels] == 3
    
    # pipeline.execute should be called 3 times
    assert mock_pipeline.execute.call_count == 3


def test_metrics_tracking():
    """Test that metrics are properly tracked with labels."""
    reset_metrics()
    
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
            "maker_taker_ratio": 0.85,
        }
    }
    
    # Export (dry-run)
    export_to_redis(
        kpis,
        redis_client=None,
        env="dev",
        exchange="bybit",
        dry_run=True,
        hash_mode=True
    )
    
    # Check labeled metrics
    labels = ("dev", "bybit", "hash")
    assert METRICS["redis_export_mode"][("dev", "bybit")] == "hash"
    assert METRICS["redis_export_keys_written_total"][labels] == 2
    assert METRICS["redis_export_batches_total"][labels] == 1
    assert METRICS["redis_export_batch_duration_ms_count"][labels] == 1
    assert METRICS["redis_export_batch_duration_ms_sum"][labels] > 0
    
    # Test metrics reset
    reset_metrics()
    assert METRICS["redis_export_batches_total"] == {}
    assert METRICS["redis_export_keys_written_total"] == {}
    assert METRICS["redis_export_batches_failed_total"] == {}


def test_print_metrics(capsys):
    """Test that print_metrics outputs correctly with labeled metrics."""
    reset_metrics()
    
    # Set labeled metrics manually
    labels = ("dev", "bybit", "hash")
    METRICS["redis_export_batches_total"][labels] = 3
    METRICS["redis_export_keys_written_total"][labels] = 10
    METRICS["redis_export_batches_failed_total"][labels] = 0
    METRICS["redis_export_batch_duration_ms_sum"][labels] = 123.45
    METRICS["redis_export_batch_duration_ms_count"][labels] = 3
    METRICS["redis_export_mode"][("dev", "bybit")] = "hash"
    
    # Print metrics
    print_metrics(show_metrics=True)
    
    # Capture output
    captured = capsys.readouterr()
    
    # Verify output contains expected labeled metrics
    assert 'redis_export_batches_total{env="dev",exchange="bybit",mode="hash"} 3' in captured.out
    assert 'redis_export_keys_written_total{env="dev",exchange="bybit",mode="hash"} 10' in captured.out
    assert 'redis_export_batch_duration_ms_sum{env="dev",exchange="bybit",mode="hash"} 123.45' in captured.out
    assert 'redis_export_batch_duration_ms_count{env="dev",exchange="bybit",mode="hash"} 3' in captured.out
    assert 'redis_export_mode{env="dev",exchange="bybit",type="hash"}' in captured.out


def test_export_error_handling():
    """Test that export handles Redis errors gracefully."""
    reset_metrics()
    
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
        }
    }
    
    # Mock Redis client that raises exception
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute.side_effect = Exception("Redis connection lost")
    
    # Export should not crash
    exported = export_to_redis(
        kpis,
        redis_client=mock_redis,
        env="dev",
        exchange="bybit",
        dry_run=False,
        hash_mode=True
    )
    
    # Export should return 0 (failed)
    assert exported == 0
    
    # Failed batch metric should be incremented (with labels)
    labels = ("dev", "bybit", "hash")
    assert METRICS["redis_export_batches_failed_total"][labels] == 1


def test_idempotent_writes():
    """Test that repeated exports are idempotent (don't change state)."""
    reset_metrics()
    
    kpis = {
        "BTCUSDT": {
            "edge_bps": 3.2,
        }
    }
    
    # First export (dry-run)
    export_to_redis(kpis, None, dry_run=True, hash_mode=True)
    keys_written_1 = METRICS["redis_export_keys_written_total"]
    
    # Reset and second export (same data)
    reset_metrics()
    export_to_redis(kpis, None, dry_run=True, hash_mode=True)
    keys_written_2 = METRICS["redis_export_keys_written_total"]
    
    # Should produce same result
    assert keys_written_1 == keys_written_2


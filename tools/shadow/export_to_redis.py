#!/usr/bin/env python3
"""
Export Soak KPIs to Redis for dry-run validation.

This module exports KPI metrics from soak/shadow phase to Redis,
enabling real-time comparison and validation workflows.

Key Schema:
    {env}:{exchange}:shadow:latest:{symbol}:{kpi}
    Example: dev:bybit:shadow:latest:BTCUSDT:edge_bps

TTL: 3600 seconds (1 hour)

Usage:
    python -m tools.shadow.export_to_redis --src artifacts/soak/latest --redis-url redis://localhost:6379/0
    python -m tools.shadow.export_to_redis --src artifacts/soak/latest --env prod --exchange bybit
    python -m tools.shadow.export_to_redis --src artifacts/soak/latest --redis-url rediss://user:pass@host:6380/0
"""

import argparse
import json
import sys
import time
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import warnings


# Prometheus-style metrics with labels (env, exchange, mode)
# Structure: {metric_name: {(env, exchange, mode): value}}
METRICS = {
    "redis_export_batches_total": {},
    "redis_export_keys_written_total": {},
    "redis_export_batches_failed_total": {},
    "redis_export_batch_duration_ms_sum": {},
    "redis_export_batch_duration_ms_count": {},
    "redis_export_mode": {},  # {(env, exchange): mode}
}


def reset_metrics():
    """Reset all metrics to initial state."""
    METRICS["redis_export_batches_total"] = {}
    METRICS["redis_export_keys_written_total"] = {}
    METRICS["redis_export_batches_failed_total"] = {}
    METRICS["redis_export_batch_duration_ms_sum"] = {}
    METRICS["redis_export_batch_duration_ms_count"] = {}
    METRICS["redis_export_mode"] = {}


def _increment_metric(metric_name: str, env: str, exchange: str, mode: str, value: float = 1.0):
    """
    Increment a labeled metric.
    
    Args:
        metric_name: Metric name
        env: Environment label
        exchange: Exchange label
        mode: Mode label (hash or flat)
        value: Value to add (default: 1.0)
    """
    labels = (env, exchange, mode)
    if labels not in METRICS[metric_name]:
        METRICS[metric_name][labels] = 0.0
    METRICS[metric_name][labels] += value


def print_metrics(show_metrics: bool = True):
    """
    Print Prometheus-style metrics with labels.
    
    Args:
        show_metrics: If True, print metrics to stdout
    """
    if not show_metrics:
        return
    
    print(f"[METRICS] Prometheus-style metrics:")
    
    # Print all labeled metrics
    for metric_name in ["redis_export_batches_total", "redis_export_keys_written_total",
                        "redis_export_batches_failed_total"]:
        for labels, value in METRICS[metric_name].items():
            env, exchange, mode = labels
            print(f"  {metric_name}{{env=\"{env}\",exchange=\"{exchange}\",mode=\"{mode}\"}} {value}")
    
    # Print Summary metrics (sum and count)
    for labels, sum_value in METRICS["redis_export_batch_duration_ms_sum"].items():
        env, exchange, mode = labels
        count_value = METRICS["redis_export_batch_duration_ms_count"].get(labels, 0)
        print(f"  redis_export_batch_duration_ms_sum{{env=\"{env}\",exchange=\"{exchange}\",mode=\"{mode}\"}} {sum_value:.2f}")
        print(f"  redis_export_batch_duration_ms_count{{env=\"{env}\",exchange=\"{exchange}\",mode=\"{mode}\"}} {count_value}")
    
    # Print mode (legacy, for compatibility)
    for labels, mode_value in METRICS["redis_export_mode"].items():
        env, exchange = labels
        print(f"  redis_export_mode{{env=\"{env}\",exchange=\"{exchange}\",type=\"{mode_value}\"}}")


def normalize_symbol(symbol: str) -> str:
    """
    Normalize symbol to A-Z0-9 only (uppercase, no separators).
    
    Args:
        symbol: Raw symbol string (e.g., "BTC-USDT", "btc/usdt", "BTCUSDT")
        
    Returns:
        Normalized symbol (e.g., "BTCUSDT")
        
    Examples:
        >>> normalize_symbol("BTC-USDT")
        'BTCUSDT'
        >>> normalize_symbol("btc/usdt")
        'BTCUSDT'
        >>> normalize_symbol("BTC_USDT")
        'BTCUSDT'
    """
    # Remove non-alphanumeric characters and convert to uppercase
    normalized = re.sub(r'[^A-Z0-9]', '', symbol.upper())
    return normalized


def build_redis_key(
    env: str,
    exchange: str,
    symbol: str,
    kpi: str
) -> str:
    """
    Build namespaced Redis key.
    
    Args:
        env: Environment (dev, staging, prod)
        exchange: Exchange name (bybit, binance, etc.)
        symbol: Trading symbol (will be normalized)
        kpi: KPI name
        
    Returns:
        Namespaced key: {env}:{exchange}:shadow:latest:{symbol}:{kpi}
        
    Examples:
        >>> build_redis_key("dev", "bybit", "BTCUSDT", "edge_bps")
        'dev:bybit:shadow:latest:BTCUSDT:edge_bps'
        >>> build_redis_key("prod", "binance", "BTC-USDT", "maker_ratio")
        'prod:binance:shadow:latest:BTCUSDT:maker_ratio'
    """
    normalized_symbol = normalize_symbol(symbol)
    return f"{env}:{exchange}:shadow:latest:{normalized_symbol}:{kpi}"


def get_redis_client(redis_url: str) -> Optional[Any]:
    """
    Get Redis client with graceful fallback.
    
    Supports:
    - redis:// - standard unencrypted connection
    - rediss:// - TLS/SSL encrypted connection
    - Authentication: redis://username:password@host:port/db
        
        Args:
            redis_url: Redis connection URL
        
    Returns:
        Redis client or None if unavailable
        
    Examples:
        >>> get_redis_client("redis://localhost:6379/0")
        <Redis client>
        >>> get_redis_client("rediss://user:pass@prod.redis.com:6380/0")
        <Redis client with TLS>
    """
    try:
        import redis
        # from_url automatically handles redis:// vs rediss:// and auth
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5
        )
        # Test connection
        client.ping()
        return client
    except ImportError:
        warnings.warn(
            "Redis library not installed. Install with: pip install redis\n"
            "Falling back to dry-run mode (no actual export).",
            RuntimeWarning
        )
        return None
    except Exception as e:
        warnings.warn(
            f"Cannot connect to Redis at {redis_url}: {e}\n"
            f"Falling back to dry-run mode (no actual export).",
            RuntimeWarning
        )
        return None


def load_iter_summaries(src_dir: Path) -> List[Dict[str, Any]]:
    """
    Load all ITER_SUMMARY_*.json files from source directory.
    
    Args:
        src_dir: Directory containing ITER_SUMMARY files
        
    Returns:
        List of iteration summary dicts
    """
    summaries = []
    iter_files = sorted(src_dir.glob("ITER_SUMMARY_*.json"))
    
    if not iter_files:
        print(f"[WARN] No ITER_SUMMARY_*.json files found in {src_dir}")
        return summaries
    
    for iter_file in iter_files:
        try:
            with open(iter_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                summaries.append(data)
        except Exception as e:
            print(f"[WARN] Failed to load {iter_file.name}: {e}")
    
    print(f"[INFO] Loaded {len(summaries)} iteration summaries")
    return summaries


def aggregate_kpis(summaries: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Aggregate KPIs by symbol from iteration summaries.
        
        Args:
        summaries: List of ITER_SUMMARY dicts
        
        Returns:
        Dict mapping symbol to aggregated KPIs
        Example: {
            "BTCUSDT": {
                "edge_bps": 3.2,
                "maker_taker_ratio": 0.85,
                "p95_latency_ms": 250,
                "risk_ratio": 0.35
            }
        }
    """
    symbol_kpis = {}
    
    for summary in summaries:
        # Extract symbol (may be at top level or in summary sub-dict)
        symbol = summary.get("symbol") or summary.get("summary", {}).get("symbol")
        if not symbol:
            continue
        
        # Extract KPIs (may be at top level or in summary sub-dict)
        kpi_data = summary.get("summary", summary)
        
        kpis = {
            "edge_bps": kpi_data.get("net_bps", 0.0),
            "maker_taker_ratio": kpi_data.get("maker_taker_ratio", 0.0),
            "p95_latency_ms": kpi_data.get("p95_latency_ms", 0.0),
            "risk_ratio": kpi_data.get("risk_ratio", 0.0),
        }
        
        # Aggregate (use latest or average - here we use latest for simplicity)
        symbol_kpis[symbol] = kpis
    
    return symbol_kpis


def export_to_redis(
    kpis: Dict[str, Dict[str, float]],
    redis_client: Optional[Any],
    env: str = "dev",
    exchange: str = "bybit",
    ttl: int = 3600,
    dry_run: bool = False,
    hash_mode: bool = True,
    batch_size: int = 50
) -> int:
    """
    Export KPIs to Redis with TTL, namespacing, and pipeline batching.
    
    Supports two storage modes:
    - Hash mode (default): All KPIs for a symbol in one hash
      HSET dev:bybit:shadow:latest:BTCUSDT edge_bps 3.2 maker_ratio 0.85
      EXPIRE dev:bybit:shadow:latest:BTCUSDT 3600
    
    - Flat mode: Each KPI as separate key
      SETEX dev:bybit:shadow:latest:BTCUSDT:edge_bps 3600 3.2
      SETEX dev:bybit:shadow:latest:BTCUSDT:maker_ratio 3600 0.85
    
    Args:
        kpis: Dict mapping symbol to KPI values
        redis_client: Redis client (or None for dry-run)
        env: Environment namespace (dev, staging, prod)
        exchange: Exchange namespace (bybit, binance, etc.)
        ttl: Time-to-live in seconds (default: 3600 = 1 hour)
        dry_run: If True, only print what would be exported
        hash_mode: If True, use HSET+EXPIRE; if False, use SETEX per key
        batch_size: Number of operations per pipeline batch
        
    Returns:
        Number of keys/symbols exported
    """
    if not kpis:
        print("[WARN] No KPIs to export")
        return 0
    
    if hash_mode:
        return _export_hash_mode(
            kpis, redis_client, env, exchange, ttl, dry_run, batch_size
        )
    else:
        return _export_flat_mode(
            kpis, redis_client, env, exchange, ttl, dry_run, batch_size
        )


def _export_hash_mode(
    kpis: Dict[str, Dict[str, float]],
    redis_client: Optional[Any],
    env: str,
    exchange: str,
    ttl: int,
    dry_run: bool,
    batch_size: int
) -> int:
    """
    Export KPIs using hash mode (HSET + EXPIRE).
    
    Each symbol gets one hash containing all KPIs.
    Uses pipeline for batching.
    """
    mode = "hash"
    start_time = time.time()
    exported_symbols = 0
    total_keys_written = 0
    
    # Update mode metric
    METRICS["redis_export_mode"][(env, exchange)] = mode
    
    # Prepare operations
    symbols = list(kpis.keys())
    
    if dry_run or redis_client is None:
        # Dry-run: just log what would be done
        for symbol in symbols:
            symbol_kpis = kpis[symbol]
            # Build base key for the hash
            base_key = f"{env}:{exchange}:shadow:latest:{normalize_symbol(symbol)}"
            
            # Show what would be written
            kpi_str = " ".join(f"{k} {v}" for k, v in symbol_kpis.items())
            print(f"[DRY-RUN] HSET {base_key} {kpi_str}")
            print(f"[DRY-RUN] EXPIRE {base_key} {ttl}")
            exported_symbols += 1
            total_keys_written += len(symbol_kpis)
        
        # Update metrics even in dry-run
        _increment_metric("redis_export_keys_written_total", env, exchange, mode, total_keys_written)
        _increment_metric("redis_export_batches_total", env, exchange, mode, 1)
        duration_ms = (time.time() - start_time) * 1000
        _increment_metric("redis_export_batch_duration_ms_sum", env, exchange, mode, duration_ms)
        _increment_metric("redis_export_batch_duration_ms_count", env, exchange, mode, 1)
        
        return exported_symbols
    
    # Real export with pipeline
    batch_count = 0
    
    for batch_start in range(0, len(symbols), batch_size):
        batch_symbols = symbols[batch_start:batch_start + batch_size]
        batch_count += 1
        
        batch_start_time = time.time()
        
        try:
            # Create pipeline (non-transactional for better performance)
            pipeline = redis_client.pipeline(transaction=False)
            
            batch_keys = 0
            for symbol in batch_symbols:
                symbol_kpis = kpis[symbol]
                base_key = f"{env}:{exchange}:shadow:latest:{normalize_symbol(symbol)}"
                
                # HSET command: set all KPIs in the hash
                # Redis expects: HSET key field1 value1 field2 value2 ...
                pipeline.hset(base_key, mapping=symbol_kpis)
                
                # EXPIRE command: set TTL for the hash
                pipeline.expire(base_key, ttl)
                
                batch_keys += len(symbol_kpis)
            
            # Execute pipeline
            results = pipeline.execute()
            
            # Count successes (HSET returns number of fields added, EXPIRE returns 1)
            success_count = sum(1 for i, r in enumerate(results) if i % 2 == 0 and r >= 0)
            fail_count = len(batch_symbols) - success_count
            
            batch_duration_ms = (time.time() - batch_start_time) * 1000
            
            # Log batch result
            print(f"[PIPELINE] batch={batch_count} symbols={len(batch_symbols)} "
                  f"keys={batch_keys} success={success_count} fail={fail_count} "
                  f"duration_ms={batch_duration_ms:.2f}")
            
            # Update labeled metrics
            _increment_metric("redis_export_batches_total", env, exchange, mode, 1)
            _increment_metric("redis_export_keys_written_total", env, exchange, mode, batch_keys)
            _increment_metric("redis_export_batch_duration_ms_sum", env, exchange, mode, batch_duration_ms)
            _increment_metric("redis_export_batch_duration_ms_count", env, exchange, mode, 1)
            
            if fail_count > 0:
                _increment_metric("redis_export_batches_failed_total", env, exchange, mode, 1)
            
            exported_symbols += success_count
            total_keys_written += batch_keys
            
        except Exception as e:
            print(f"[ERROR] Batch {batch_count} failed: {e}")
            _increment_metric("redis_export_batches_failed_total", env, exchange, mode, 1)
    
    return exported_symbols


def _export_flat_mode(
    kpis: Dict[str, Dict[str, float]],
    redis_client: Optional[Any],
    env: str,
    exchange: str,
    ttl: int,
    dry_run: bool,
    batch_size: int
) -> int:
    """
    Export KPIs using flat mode (SETEX per key).
    
    Each KPI gets its own key with SETEX.
    Uses pipeline for batching.
    """
    mode = "flat"
    start_time = time.time()
    exported_count = 0
    
    # Update mode metric
    METRICS["redis_export_mode"][(env, exchange)] = mode
    
    # Flatten KPIs into individual key-value pairs
    all_operations = []
    for symbol, symbol_kpis in kpis.items():
        for kpi_name, kpi_value in symbol_kpis.items():
            key = build_redis_key(env, exchange, symbol, kpi_name)
            value = str(kpi_value)
            all_operations.append((key, value))
    
    if dry_run or redis_client is None:
        # Dry-run: just log what would be done
        for key, value in all_operations:
            print(f"[DRY-RUN] SETEX {key} {ttl} {value}")
            exported_count += 1
        
        # Update metrics even in dry-run
        _increment_metric("redis_export_keys_written_total", env, exchange, mode, exported_count)
        _increment_metric("redis_export_batches_total", env, exchange, mode, 1)
        duration_ms = (time.time() - start_time) * 1000
        _increment_metric("redis_export_batch_duration_ms_sum", env, exchange, mode, duration_ms)
        _increment_metric("redis_export_batch_duration_ms_count", env, exchange, mode, 1)
        
        return exported_count
    
    # Real export with pipeline
    batch_count = 0
    
    for batch_start in range(0, len(all_operations), batch_size):
        batch_ops = all_operations[batch_start:batch_start + batch_size]
        batch_count += 1
        
        batch_start_time = time.time()
        
        try:
            # Create pipeline (non-transactional)
            pipeline = redis_client.pipeline(transaction=False)
            
            for key, value in batch_ops:
                pipeline.setex(key, ttl, value)
            
            # Execute pipeline
            results = pipeline.execute()
            
            # Count successes (SETEX returns True on success)
            success_count = sum(1 for r in results if r)
            fail_count = len(batch_ops) - success_count
            
            batch_duration_ms = (time.time() - batch_start_time) * 1000
            
            # Log batch result
            print(f"[PIPELINE] batch={batch_count} keys={len(batch_ops)} "
                  f"success={success_count} fail={fail_count} "
                  f"duration_ms={batch_duration_ms:.2f}")
            
            # Update labeled metrics
            _increment_metric("redis_export_batches_total", env, exchange, mode, 1)
            _increment_metric("redis_export_keys_written_total", env, exchange, mode, len(batch_ops))
            _increment_metric("redis_export_batch_duration_ms_sum", env, exchange, mode, batch_duration_ms)
            _increment_metric("redis_export_batch_duration_ms_count", env, exchange, mode, 1)
            
            if fail_count > 0:
                _increment_metric("redis_export_batches_failed_total", env, exchange, mode, 1)
            
            exported_count += success_count
        
        except Exception as e:
            print(f"[ERROR] Batch {batch_count} failed: {e}")
            _increment_metric("redis_export_batches_failed_total", env, exchange, mode, 1)
    
    return exported_count


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export soak KPIs to Redis for dry-run validation"
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=Path("artifacts/soak/latest"),
        help="Source directory with ITER_SUMMARY_*.json files (default: artifacts/soak/latest)"
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default="redis://localhost:6379/0",
        help="Redis connection URL (default: redis://localhost:6379/0)"
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=3600,
        help="TTL for Redis keys in seconds (default: 3600 = 1 hour)"
    )
    parser.add_argument(
        "--env",
        type=str,
        default="dev",
        choices=["dev", "staging", "prod"],
        help="Environment namespace (default: dev)"
    )
    parser.add_argument(
        "--exchange",
        type=str,
        default="bybit",
        help="Exchange namespace (default: bybit)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode: print what would be exported without actually exporting"
    )
    
    # Storage mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--hash-mode",
        dest="hash_mode",
        action="store_true",
        default=True,
        help="Use hash mode: HSET + EXPIRE (default, more efficient)"
    )
    mode_group.add_argument(
        "--flat-keys",
        dest="hash_mode",
        action="store_false",
        help="Use flat mode: SETEX per key (legacy compatibility)"
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of operations per pipeline batch (default: 50)"
    )
    
    parser.add_argument(
        "--show-metrics",
        action="store_true",
        help="Print Prometheus-style metrics after export"
    )
    
    args = parser.parse_args()
    
    # Reset metrics for this run
    reset_metrics()
    
    # Validate source directory
    if not args.src.exists():
        print(f"[ERROR] Source directory not found: {args.src}")
        return 1
    
    # Load iteration summaries
    print(f"[INFO] Loading summaries from: {args.src}")
    summaries = load_iter_summaries(args.src)
    
    if not summaries:
        print("[ERROR] No iteration summaries found")
        return 1
    
    # Aggregate KPIs by symbol
    print("[INFO] Aggregating KPIs by symbol...")
    kpis = aggregate_kpis(summaries)
    
    if not kpis:
        print("[ERROR] No KPIs extracted from summaries")
        return 1
    
    print(f"[INFO] Aggregated KPIs for {len(kpis)} symbols")
    for symbol, symbol_kpis in kpis.items():
        print(f"  {symbol}: {len(symbol_kpis)} KPIs")
    
    # Get Redis client
    redis_client = None
    if not args.dry_run:
        print(f"[INFO] Connecting to Redis: {args.redis_url}")
        redis_client = get_redis_client(args.redis_url)
        
        if redis_client is None:
            print("[WARN] Redis unavailable, falling back to dry-run mode")
            args.dry_run = True
    
    # Export to Redis
    mode_str = "hash" if args.hash_mode else "flat"
    print(f"[INFO] Exporting KPIs to Redis (env={args.env}, exchange={args.exchange}, "
          f"mode={mode_str}, batch_size={args.batch_size}, TTL={args.ttl}s)...")
    
    exported_count = export_to_redis(
        kpis,
        redis_client,
        env=args.env,
        exchange=args.exchange,
        ttl=args.ttl,
        dry_run=args.dry_run,
        hash_mode=args.hash_mode,
        batch_size=args.batch_size
    )
    
    if args.dry_run:
        if args.hash_mode:
            print(f"[DRY-RUN] Would export {len(kpis)} symbols ({METRICS['redis_export_keys_written_total']} total KPIs)")
        else:
            print(f"[DRY-RUN] Would export {METRICS['redis_export_keys_written_total']} keys")
    else:
        if args.hash_mode:
            print(f"[SUCCESS] Exported {exported_count} symbols ({METRICS['redis_export_keys_written_total']} total KPIs) to Redis")
        else:
            print(f"[SUCCESS] Exported {exported_count} keys to Redis")
    
    # Print metrics if requested
    if args.show_metrics:
        print()
        print_metrics(show_metrics=True)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

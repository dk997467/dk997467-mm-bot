#!/usr/bin/env python3
"""
Export Soak Violations to Redis

Reads VIOLATIONS.json and SOAK_SUMMARY.json and publishes to Redis:
- Hash per symbol: {env}:{exchange}:soak:violations:{symbol}
- Stream (optional): {env}:{exchange}:soak:violations:stream:{symbol}

Usage:
    python -m tools.soak.export_violations_to_redis \
      --summary reports/analysis/SOAK_SUMMARY.json \
      --violations reports/analysis/VIOLATIONS.json \
      --env prod --exchange bybit \
      --redis-url rediss://user:pass@host:6379/0
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List


def get_redis_client(redis_url: str, timeout: int = 5) -> Optional[Any]:
    """
    Get Redis client with TLS and auth support.
    
    Returns None if Redis is unavailable (graceful fallback).
    """
    try:
        import redis
    except ImportError:
        print("[WARN] redis library not found, skipping export")
        print("[HINT] pip install redis")
        return None
    
    try:
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=timeout,
            socket_connect_timeout=timeout
        )
        # Test connection
        client.ping()
        return client
    except Exception as e:
        try:
            print(f"[WARN] Cannot connect to Redis: {e}")
        except UnicodeEncodeError:
            print(f"[WARN] Cannot connect to Redis: {type(e).__name__}")
        return None


def export_violations_hash(
    client: Any,
    summary: Dict[str, Any],
    violations: List[Dict[str, Any]],
    env: str,
    exchange: str,
    ttl: int
) -> int:
    """
    Export violations as Redis hash per symbol.
    
    Returns:
        Number of symbols exported
    """
    exported = 0
    
    for symbol, metrics in summary.get("symbols", {}).items():
        # Count violations for this symbol
        symbol_violations = [v for v in violations if v.get("symbol") == symbol]
        crit_count = len([v for v in symbol_violations if v.get("level") == "CRIT"])
        warn_count = len([v for v in symbol_violations if v.get("level") == "WARN"])
        
        # Build hash key
        hash_key = f"{env}:{exchange}:soak:violations:{symbol}"
        
        # Extract last values
        edge_last = metrics.get("edge_bps", {}).get("last", 0)
        maker_last = metrics.get("maker_taker_ratio", {}).get("last", 0)
        lat_last = metrics.get("p95_latency_ms", {}).get("last", 0)
        risk_last = metrics.get("risk_ratio", {}).get("last", 0)
        
        # Determine verdict for this symbol
        if crit_count > 0:
            verdict = "CRIT"
        elif warn_count > 0:
            verdict = "WARN"
        else:
            verdict = "OK"
        
        # Hash data
        hash_data = {
            "crit_count": crit_count,
            "warn_count": warn_count,
            "last_edge": edge_last,
            "last_maker_taker": maker_last,
            "last_latency_p95": lat_last,
            "last_risk": risk_last,
            "verdict": verdict,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        try:
            # Use pipeline for atomic HSET + EXPIRE
            pipe = client.pipeline(transaction=False)
            pipe.hset(hash_key, mapping=hash_data)
            pipe.expire(hash_key, ttl)
            pipe.execute()
            
            exported += 1
            print(f"[INFO] Exported {symbol}: {verdict} (crit={crit_count}, warn={warn_count})")
        except Exception as e:
            print(f"[ERROR] Failed to export {symbol}: {e}")
    
    return exported


def export_violations_stream(
    client: Any,
    violations: List[Dict[str, Any]],
    env: str,
    exchange: str,
    stream_maxlen: int = 5000
) -> int:
    """
    Export violations as Redis stream events with retention.
    
    Args:
        client: Redis client
        violations: List of violations
        env: Environment (e.g., dev, prod)
        exchange: Exchange (e.g., bybit)
        stream_maxlen: Maximum stream length (default: 5000)
    
    Returns:
        Number of events exported
    """
    exported = 0
    streams_seen = set()
    
    for violation in violations:
        symbol = violation.get("symbol")
        metric = violation.get("metric")
        level = violation.get("level")
        value = violation.get("value")
        threshold = violation.get("threshold")
        window_index = violation.get("window_index", 0)
        note = violation.get("note", "")
        
        # Build stream key
        stream_key = f"{env}:{exchange}:soak:violations:stream:{symbol}"
        streams_seen.add(stream_key)
        
        # Stream entry
        entry = {
            "metric": metric,
            "level": level,
            "value": str(value),
            "threshold": str(threshold),
            "window_index": str(window_index),
            "note": note,
            "ts": datetime.now(timezone.utc).isoformat()
        }
        
        try:
            # Use approximate MAXLEN for performance
            client.xadd(stream_key, entry, maxlen=stream_maxlen, approximate=True)
            exported += 1
        except Exception as e:
            print(f"[ERROR] Failed to export stream event for {symbol}/{metric}: {e}")
    
    # Explicit XTRIM for all streams (ensure retention)
    for stream_key in streams_seen:
        try:
            client.xtrim(stream_key, maxlen=stream_maxlen, approximate=True)
        except Exception as e:
            print(f"[WARN] Failed to trim stream {stream_key}: {e}")
    
    return exported


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export soak violations to Redis"
    )
    
    parser.add_argument(
        "--summary",
        type=Path,
        required=True,
        help="Path to SOAK_SUMMARY.json"
    )
    parser.add_argument(
        "--violations",
        type=Path,
        required=True,
        help="Path to VIOLATIONS.json"
    )
    parser.add_argument(
        "--env",
        type=str,
        default="dev",
        help="Environment (e.g., dev, prod)"
    )
    parser.add_argument(
        "--exchange",
        type=str,
        default="bybit",
        help="Exchange (e.g., bybit, kucoin)"
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default="redis://localhost:6379/0",
        help="Redis URL (supports rediss:// for TLS)"
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=3600,
        help="TTL for hash keys (seconds, default: 3600)"
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Also export violations as stream events"
    )
    parser.add_argument(
        "--stream-maxlen",
        type=int,
        default=5000,
        help="Maximum stream length (default: 5000, for retention)"
    )
    
    args = parser.parse_args()
    
    # Load summary
    if not args.summary.exists():
        print(f"[ERROR] Summary not found: {args.summary}")
        return 1
    
    try:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] Failed to load summary: {e}")
        return 1
    
    # Load violations
    if not args.violations.exists():
        print(f"[ERROR] Violations not found: {args.violations}")
        return 1
    
    try:
        violations = json.loads(args.violations.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] Failed to load violations: {e}")
        return 1
    
    # Get Redis client
    print(f"[INFO] Connecting to Redis: {args.redis_url}")
    client = get_redis_client(args.redis_url)
    
    if client is None:
        print("[WARN] Redis unavailable, skipping export (graceful fallback)")
        return 1  # Graceful skip - not critical but signal that export didn't happen
    
    # Export hash per symbol
    print(f"[INFO] Exporting violations hash (env={args.env}, exchange={args.exchange})")
    hash_count = export_violations_hash(
        client,
        summary,
        violations,
        args.env,
        args.exchange,
        args.ttl
    )
    
    print(f"[INFO] Exported {hash_count} hash keys")
    
    # Export stream (optional)
    if args.stream:
        print(f"[INFO] Exporting violations stream (maxlen={args.stream_maxlen})")
        stream_count = export_violations_stream(
            client,
            violations,
            args.env,
            args.exchange,
            stream_maxlen=args.stream_maxlen
        )
        print(f"[INFO] Exported {stream_count} stream events (retention: {args.stream_maxlen})")
    
    print("[INFO] Export complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())


"""
Export SOAK_SUMMARY.json to Redis

Экспорт snapshot summary в Redis для real-time мониторинга.
Graceful fallback при недоступности Redis.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# Conditional Redis import
try:
    import redis
    from redis.exceptions import ConnectionError, TimeoutError
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    ConnectionError = Exception
    TimeoutError = Exception
    REDIS_AVAILABLE = False


def get_redis_client(redis_url: str) -> Optional[any]:
    """Get Redis client with graceful fallback."""
    if not REDIS_AVAILABLE:
        print("[WARN] Redis library not available", file=sys.stderr)
        return None
    
    try:
        client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=5)
        client.ping()
        return client
    except (ConnectionError, TimeoutError) as e:
        print(f"[WARN] Redis unavailable: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] Unexpected error connecting to Redis: {e}", file=sys.stderr)
        return None


def export_summary(
    summary_path: Path,
    env: str,
    exchange: str,
    redis_url: str,
    ttl: int
) -> bool:
    """
    Export SOAK_SUMMARY.json to Redis.
    
    Returns:
        True if successful, False if skipped (graceful degrade)
    """
    if not summary_path.exists():
        print(f"[WARN] Summary not found: {summary_path}", file=sys.stderr)
        return False
    
    try:
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"[ERROR] Failed to load summary: {e}", file=sys.stderr)
        return False
    
    # Get Redis client
    client = get_redis_client(redis_url)
    if not client:
        print("[WARN] Redis unavailable, skip export", file=sys.stderr)
        return False
    
    # Build Redis key
    hash_key = f"{env}:{exchange}:soak:summary"
    
    try:
        # Export as hash (all fields)
        overall = summary.get("overall", {})
        hash_data = {
            "windows": str(summary.get("windows", 0)),
            "verdict": overall.get("verdict", "N/A"),
            "crit_count": str(overall.get("crit_count", 0)),
            "warn_count": str(overall.get("warn_count", 0)),
            "ok_count": str(overall.get("ok_count", 0)),
            "symbols": str(len(summary.get("symbols", {}))),
            "generated_at": summary.get("generated_at_utc", ""),
            "updated_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }
        
        # Optional: Add meta fields if present
        meta = summary.get("meta", {})
        if meta:
            hash_data["commit_range"] = meta.get("commit_range", "")
            hash_data["profile"] = meta.get("profile", "")
        
        client.hset(hash_key, mapping=hash_data)
        client.expire(hash_key, ttl)
        
        print(f"[INFO] Exported summary to {hash_key} (TTL={ttl}s)", file=sys.stderr)
        return True
    
    except Exception as e:
        print(f"[WARN] Failed to export summary: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Export SOAK_SUMMARY.json to Redis")
    parser.add_argument("--summary", type=Path, required=True, help="Path to SOAK_SUMMARY.json")
    parser.add_argument("--env", default="dev", help="Environment (dev/prod)")
    parser.add_argument("--exchange", default="bybit", help="Exchange")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0", help="Redis URL")
    parser.add_argument("--ttl", type=int, default=3600, help="TTL for keys (seconds)")
    
    args = parser.parse_args()
    
    success = export_summary(
        args.summary,
        args.env,
        args.exchange,
        args.redis_url,
        args.ttl
    )
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())


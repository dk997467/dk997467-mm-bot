#!/usr/bin/env python3
"""
Export Live summary to Redis with TTL refresh.

Usage:
    python -m tools.live.export_live_summary \\
        --src artifacts/live/latest \\
        --redis-url rediss://... \\
        --env prod --exchange bybit \\
        --ttl 3600
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict

try:
    import redis
except ImportError:
    redis = None

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def export_to_redis(
    redis_client: "redis.Redis",
    env: str,
    exchange: str,
    summary: Dict,
    ttl: int
) -> None:
    """Export live summary to Redis."""
    # Global state
    state_key = f"{env}:{exchange}:live:state"
    redis_client.set(state_key, summary["live_state"], ex=ttl)
    logger.info(f"Exported: {state_key} = {summary['live_state']}")
    
    # Per-symbol throttle
    for sym, throttle in summary["per_symbol_throttle"].items():
        throttle_key = f"{env}:{exchange}:live:throttle:{sym}"
        redis_client.set(throttle_key, str(throttle), ex=ttl)
        logger.debug(f"Exported: {throttle_key} = {throttle}")
    
    # Summary hash
    summary_key = f"{env}:{exchange}:live:summary"
    redis_client.hset(summary_key, mapping={
        "state": summary["live_state"],
        "throttle_factor": str(summary["throttle_factor"]),
        "symbols_count": str(summary["meta"]["symbols_count"]),
        "active_count": str(summary["meta"]["active_count"]),
        "frozen_count": str(summary["meta"]["frozen_count"]),
        "generated_at_utc": summary["generated_at_utc"]
    })
    redis_client.expire(summary_key, ttl)
    logger.info(f"Exported: {summary_key} (hash)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export live summary to Redis")
    parser.add_argument(
        "--src",
        type=Path,
        default=Path("artifacts/live/latest"),
        help="Source directory with LIVE_SUMMARY.json"
    )
    parser.add_argument("--redis-url", required=True, help="Redis URL")
    parser.add_argument("--env", required=True, choices=["dev", "staging", "prod"])
    parser.add_argument("--exchange", default="bybit", help="Exchange name")
    parser.add_argument("--ttl", type=int, default=3600, help="TTL in seconds")
    parser.add_argument("--verbose", action="store_true")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("=" * 60)
    logger.info("Export Live Summary to Redis")
    logger.info("=" * 60)
    
    # Load summary
    summary_path = args.src / "LIVE_SUMMARY.json"
    if not summary_path.exists():
        logger.error(f"Summary not found: {summary_path}")
        return 1
    
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    logger.info(f"Loaded summary: state={summary['live_state']}, throttle={summary['throttle_factor']}")
    
    # Connect to Redis
    if redis is None:
        logger.error("redis-py not installed")
        return 1
    
    try:
        redis_client = redis.from_url(args.redis_url, decode_responses=True)
        redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        return 1
    
    # Export
    try:
        export_to_redis(redis_client, args.env, args.exchange, summary, args.ttl)
        logger.info("✅ Export complete")
        return 0
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())


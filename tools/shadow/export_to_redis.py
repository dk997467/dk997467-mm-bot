#!/usr/bin/env python3
"""
Export Soak KPIs to Redis for dry-run validation.

This module exports KPI metrics from soak/shadow phase to Redis,
enabling real-time comparison and validation workflows.

Key Schema:
    shadow:latest:{symbol}:{kpi}
    Example: shadow:latest:BTCUSDT:edge_bps

TTL: 3600 seconds (1 hour)

Usage:
    python -m tools.shadow.export_to_redis --src artifacts/soak/latest --redis-url redis://localhost:6379/0
    python -m tools.shadow.export_to_redis --src artifacts/soak/latest  # Uses default Redis URL
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
import warnings


def get_redis_client(redis_url: str) -> Optional[Any]:
    """
    Get Redis client with graceful fallback.
    
    Args:
        redis_url: Redis connection URL
        
    Returns:
        Redis client or None if unavailable
    """
    try:
        import redis
        client = redis.from_url(redis_url, decode_responses=True)
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
    ttl: int = 3600,
    dry_run: bool = False
) -> int:
    """
    Export KPIs to Redis with TTL.
    
    Args:
        kpis: Dict mapping symbol to KPI values
        redis_client: Redis client (or None for dry-run)
        ttl: Time-to-live in seconds (default: 3600 = 1 hour)
        dry_run: If True, only print what would be exported
        
    Returns:
        Number of keys exported
    """
    if not kpis:
        print("[WARN] No KPIs to export")
        return 0
    
    exported_count = 0
    
    for symbol, symbol_kpis in kpis.items():
        for kpi_name, kpi_value in symbol_kpis.items():
            key = f"shadow:latest:{symbol}:{kpi_name}"
            value = str(kpi_value)
            
            if dry_run or redis_client is None:
                print(f"[DRY-RUN] Would export: {key} = {value} (TTL={ttl}s)")
            else:
                try:
                    redis_client.setex(key, ttl, value)
                    print(f"[EXPORT] {key} = {value} (TTL={ttl}s)")
                    exported_count += 1
                except Exception as e:
                    print(f"[ERROR] Failed to export {key}: {e}")
    
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
        "--dry-run",
        action="store_true",
        help="Dry-run mode: print what would be exported without actually exporting"
    )
    
    args = parser.parse_args()
    
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
    print(f"[INFO] Exporting KPIs to Redis (TTL={args.ttl}s)...")
    exported_count = export_to_redis(kpis, redis_client, args.ttl, args.dry_run)
    
    if args.dry_run:
        total_keys = sum(len(v) for v in kpis.values())
        print(f"[DRY-RUN] Would export {total_keys} keys")
    else:
        print(f"[SUCCESS] Exported {exported_count} keys to Redis")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

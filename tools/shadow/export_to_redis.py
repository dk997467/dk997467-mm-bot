#!/usr/bin/env python3
"""
Shadow Mode → Redis KPI Exporter

Publishes Shadow Mode KPIs to Redis for downstream consumption (e.g., Dry-Run mode).

Architecture:
    Shadow Mode → POST_SHADOW_SNAPSHOT.json → Redis Hash/Stream → Dry-Run Consumer

Usage:
    python -m tools.shadow.export_to_redis --src artifacts/shadow/latest
    
    # With custom Redis URL
    python -m tools.shadow.export_to_redis --src artifacts/shadow/latest --redis-url redis://localhost:6379
    
    # Stream mode (for time-series data)
    python -m tools.shadow.export_to_redis --src artifacts/shadow/latest --mode stream
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


class RedisKPIExporter:
    """Exports Shadow Mode KPIs to Redis."""
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        mode: str = "hash",  # "hash" or "stream"
        ttl_seconds: int = 86400,  # 24 hours
    ):
        """
        Initialize Redis KPI Exporter.
        
        Args:
            redis_url: Redis connection URL
            mode: Export mode - "hash" (latest snapshot) or "stream" (time-series)
            ttl_seconds: TTL for hash keys (default: 24h)
        """
        if not REDIS_AVAILABLE:
            raise ImportError("redis library not installed. Run: pip install redis")
        
        self.redis_url = redis_url
        self.mode = mode
        self.ttl_seconds = ttl_seconds
        
        # Connect to Redis
        try:
            self.client = redis.from_url(redis_url)
            self.client.ping()
            logger.info(f"✓ Connected to Redis: {redis_url}")
        except Exception as e:
            logger.error(f"✗ Failed to connect to Redis: {e}")
            raise
    
    def export_snapshot(self, snapshot: Dict[str, Any], symbol: str = "ALL") -> bool:
        """
        Export a snapshot to Redis.
        
        Args:
            snapshot: POST_SHADOW_SNAPSHOT.json data
            symbol: Symbol identifier (default: ALL for aggregated data)
        
        Returns:
            True if export successful, False otherwise
        """
        try:
            ts = int(time.time())
            timestamp_iso = datetime.now(timezone.utc).isoformat()
            
            # Build export payload
            payload = {
                "timestamp": timestamp_iso,
                "timestamp_unix": ts,
                "symbol": symbol,
                "maker_taker_ratio": snapshot.get("maker_taker_ratio", 0.0),
                "net_bps": snapshot.get("net_bps", 0.0),
                "p95_latency_ms": snapshot.get("p95_latency_ms", 0.0),
                "risk_ratio": snapshot.get("risk_ratio", 0.0),
                "slippage_p95": snapshot.get("slippage_p95", 0.0),
                "adverse_p95": snapshot.get("adverse_p95", 0.0),
                "maker_count": snapshot.get("maker_count", 0),
                "taker_count": snapshot.get("taker_count", 0),
                "total_fills": snapshot.get("total_fills", 0),
                "mode": "shadow",
            }
            
            if self.mode == "hash":
                # Store as hash (latest snapshot)
                key = f"shadow:kpi:{symbol.lower()}"
                
                # Convert payload to flat string values for HSET
                flat_payload = {k: str(v) for k, v in payload.items()}
                
                # HSET with all fields
                self.client.hset(key, mapping=flat_payload)
                
                # Set TTL
                self.client.expire(key, self.ttl_seconds)
                
                logger.info(f"✓ Exported to Redis hash: {key} (TTL: {self.ttl_seconds}s)")
                
            elif self.mode == "stream":
                # Store as stream entry (time-series)
                stream_key = f"shadow:kpi:stream:{symbol.lower()}"
                
                # XADD to stream
                msg_id = self.client.xadd(stream_key, payload, maxlen=10000)  # Keep last 10k entries
                
                logger.info(f"✓ Exported to Redis stream: {stream_key} (msg_id: {msg_id.decode()})")
            
            else:
                logger.error(f"✗ Invalid mode: {self.mode} (expected 'hash' or 'stream')")
                return False
            
            return True
        
        except Exception as e:
            logger.error(f"✗ Failed to export snapshot: {e}")
            return False
    
    def export_per_symbol(self, summaries: list, symbols: list) -> int:
        """
        Export per-symbol KPIs from iteration summaries.
        
        Args:
            summaries: List of ITER_SUMMARY_*.json dicts
            symbols: List of symbols to export
        
        Returns:
            Number of successfully exported symbols
        """
        exported_count = 0
        
        for symbol in symbols:
            # Filter summaries for this symbol
            symbol_summaries = [s for s in summaries if s.get("symbol") == symbol]
            
            if not symbol_summaries:
                logger.warning(f"⚠ No summaries found for symbol: {symbol}")
                continue
            
            # Compute aggregated KPIs for this symbol
            maker_counts = [s.get("maker_count", 0) for s in symbol_summaries]
            taker_counts = [s.get("taker_count", 0) for s in symbol_summaries]
            latencies = [s.get("p95_latency_ms", 0) for s in symbol_summaries]
            net_bps_vals = [s.get("net_bps", 0) for s in symbol_summaries]
            risk_vals = [s.get("risk_ratio", 0) for s in symbol_summaries]
            
            total_maker = sum(maker_counts)
            total_taker = sum(taker_counts)
            total_fills = total_maker + total_taker
            
            maker_taker_ratio = total_maker / total_fills if total_fills > 0 else 0.0
            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
            avg_net_bps = sum(net_bps_vals) / len(net_bps_vals) if net_bps_vals else 0.0
            avg_risk = sum(risk_vals) / len(risk_vals) if risk_vals else 0.0
            
            # Build snapshot for this symbol
            snapshot = {
                "maker_taker_ratio": maker_taker_ratio,
                "net_bps": avg_net_bps,
                "p95_latency_ms": avg_latency,
                "risk_ratio": avg_risk,
                "maker_count": total_maker,
                "taker_count": total_taker,
                "total_fills": total_fills,
            }
            
            # Export to Redis
            if self.export_snapshot(snapshot, symbol=symbol):
                exported_count += 1
        
        return exported_count
    
    def close(self):
        """Close Redis connection."""
        if self.client:
            self.client.close()
            logger.info("✓ Closed Redis connection")


def load_snapshot(src_dir: Path) -> Optional[Dict]:
    """Load POST_SHADOW_SNAPSHOT.json."""
    snapshot_file = src_dir / "reports/analysis/POST_SHADOW_SNAPSHOT.json"
    
    if not snapshot_file.exists():
        logger.warning(f"⚠ Snapshot not found: {snapshot_file}")
        return None
    
    try:
        with open(snapshot_file, 'r') as f:
            snapshot = json.load(f)
        
        logger.info(f"✓ Loaded snapshot: {snapshot_file}")
        return snapshot
    
    except Exception as e:
        logger.error(f"✗ Failed to load snapshot: {e}")
        return None


def load_iteration_summaries(src_dir: Path) -> list:
    """Load all ITER_SUMMARY_*.json files."""
    summaries = []
    
    iter_files = sorted(src_dir.glob("ITER_SUMMARY_*.json"))
    
    if not iter_files:
        logger.warning(f"⚠ No ITER_SUMMARY files found in {src_dir}")
        return summaries
    
    for iter_file in iter_files:
        try:
            with open(iter_file, 'r') as f:
                summary = json.load(f)
            
            summaries.append(summary)
        
        except Exception as e:
            logger.warning(f"⚠ Failed to load {iter_file.name}: {e}")
    
    logger.info(f"✓ Loaded {len(summaries)} iteration summaries")
    return summaries


def main():
    parser = argparse.ArgumentParser(
        description="Export Shadow Mode KPIs to Redis"
    )
    parser.add_argument(
        "--src",
        type=str,
        default="artifacts/shadow/latest",
        help="Source directory (default: artifacts/shadow/latest)"
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default="redis://localhost:6379",
        help="Redis connection URL (default: redis://localhost:6379)"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["hash", "stream"],
        default="hash",
        help="Export mode: hash (latest snapshot) or stream (time-series) (default: hash)"
    )
    parser.add_argument(
        "--per-symbol",
        action="store_true",
        help="Export per-symbol KPIs (in addition to aggregated)"
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=86400,
        help="TTL for hash keys in seconds (default: 86400 = 24h)"
    )
    
    args = parser.parse_args()
    
    # Check Redis availability
    if not REDIS_AVAILABLE:
        logger.error("✗ Redis library not installed. Run: pip install redis")
        sys.exit(1)
    
    # Resolve source directory
    src_dir = Path(args.src)
    if not src_dir.exists():
        logger.error(f"✗ Source directory not found: {src_dir}")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("SHADOW → REDIS KPI EXPORT")
    logger.info("=" * 60)
    logger.info(f"Source: {src_dir}")
    logger.info(f"Redis URL: {args.redis_url}")
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Per-Symbol: {args.per_symbol}")
    logger.info("")
    
    try:
        # Initialize exporter
        exporter = RedisKPIExporter(
            redis_url=args.redis_url,
            mode=args.mode,
            ttl_seconds=args.ttl
        )
        
        # Load snapshot
        snapshot = load_snapshot(src_dir)
        
        if not snapshot:
            logger.warning("⚠ No snapshot available - loading iteration summaries")
            summaries = load_iteration_summaries(src_dir)
            
            if not summaries:
                logger.error("✗ No data available to export")
                exporter.close()
                sys.exit(1)
            
            # Build snapshot from last 8 iterations
            last_8 = summaries[-8:] if len(summaries) >= 8 else summaries
            
            maker_counts = [s.get("maker_count", 0) for s in last_8]
            taker_counts = [s.get("taker_count", 0) for s in last_8]
            latencies = [s.get("p95_latency_ms", 0) for s in last_8]
            net_bps_vals = [s.get("net_bps", 0) for s in last_8]
            risk_vals = [s.get("risk_ratio", 0) for s in last_8]
            
            total_maker = sum(maker_counts)
            total_taker = sum(taker_counts)
            total_fills = total_maker + total_taker
            
            snapshot = {
                "maker_taker_ratio": total_maker / total_fills if total_fills > 0 else 0.0,
                "net_bps": sum(net_bps_vals) / len(net_bps_vals) if net_bps_vals else 0.0,
                "p95_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
                "risk_ratio": sum(risk_vals) / len(risk_vals) if risk_vals else 0.0,
                "maker_count": total_maker,
                "taker_count": total_taker,
                "total_fills": total_fills,
            }
            
            logger.info(f"✓ Built snapshot from last {len(last_8)} iterations")
        
        # Export aggregated snapshot
        success = exporter.export_snapshot(snapshot, symbol="ALL")
        
        if not success:
            logger.error("✗ Failed to export aggregated snapshot")
            exporter.close()
            sys.exit(1)
        
        # Export per-symbol KPIs if requested
        if args.per_symbol:
            summaries = load_iteration_summaries(src_dir)
            
            if summaries:
                # Extract unique symbols
                symbols = set(s.get("symbol", "UNKNOWN") for s in summaries)
                symbols.discard("UNKNOWN")
                
                logger.info(f"Exporting per-symbol KPIs for {len(symbols)} symbols...")
                
                exported = exporter.export_per_symbol(summaries, list(symbols))
                
                logger.info(f"✓ Exported {exported}/{len(symbols)} symbols")
        
        # Close connection
        exporter.close()
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("✅ EXPORT COMPLETE")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Verify with:")
        logger.info(f"  redis-cli -u {args.redis_url} HGETALL shadow:kpi:all")
        if args.mode == "stream":
            logger.info(f"  redis-cli -u {args.redis_url} XREAD COUNT 10 STREAMS shadow:kpi:stream:all 0")
        logger.info("")
        
        sys.exit(0)
    
    except KeyboardInterrupt:
        logger.warning("⚠ Export interrupted by user")
        sys.exit(130)
    
    except Exception as e:
        logger.exception(f"✗ Unhandled error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()


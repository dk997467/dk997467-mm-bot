"""
Research data recorder for offline analysis and backtesting.

Records comprehensive market data, order events, and PnL attribution
for research purposes using Parquet/CSV format with hourly rotation.
"""

import asyncio
import json
import logging
import gzip
import numpy as np
try:
    import zstandard as zstd
except ImportError:
    zstd = None
import os
import random
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Literal
from decimal import Decimal
from collections import defaultdict, deque

import polars as pl
from dataclasses import dataclass, asdict

from src.common.config import AppConfig, get_git_sha, cfg_hash_sanitized
from src.common.models import Order, OrderBook, Trade, Side
from src.common.utils import json_dumps, round_floats
from src.storage.validators import validate_summary_payload, upgrade_summary
from src.storage.locks import acquire_hour_lock

logger = logging.getLogger(__name__)

# Prometheus metrics (assuming prometheus_client is available)
try:
    from prometheus_client import Counter
    summaries_written_total = Counter('summaries_written_total', 'Total summaries written', ['symbol'])
    summaries_pruned_total = Counter('summaries_pruned_total', 'Total summary files pruned', ['symbol'])
    summary_write_errors_total = Counter('summary_write_errors_total', 'Total summary write errors', ['symbol'])
    prometheus_available = True
except ImportError:
    logger.warning("prometheus_client not available, metrics disabled")
    prometheus_available = False
    # Create mock counters
    class MockCounter:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kwargs): return self
        def inc(self, amount=1): pass
    
    summaries_written_total = MockCounter()
    summaries_pruned_total = MockCounter()
    summary_write_errors_total = MockCounter()


@dataclass
class ResearchRecord:
    """Research data record with all necessary fields for analysis."""
    # Timestamp and market data
    ts: datetime
    symbol: str
    mid: float
    best_bid: float
    best_ask: float
    spread: float
    vola_1m: float
    ob_imbalance: float
    
    # Our quotes (prices/sizes per level)
    our_bid_1: Optional[float] = None
    our_bid_1_size: Optional[float] = None
    our_bid_2: Optional[float] = None
    our_bid_2_size: Optional[float] = None
    our_bid_3: Optional[float] = None
    our_bid_3_size: Optional[float] = None
    
    our_ask_1: Optional[float] = None
    our_ask_1_size: Optional[float] = None
    our_ask_2: Optional[float] = None
    our_ask_2_size: Optional[float] = None
    our_ask_3: Optional[float] = None
    our_ask_3_size: Optional[float] = None
    
    # Order events
    event_type: Optional[str] = None  # create/cancel/replace/fill
    order_id: Optional[str] = None
    side: Optional[str] = None
    price: Optional[float] = None
    qty: Optional[float] = None
    
    # Fill details
    fill_price: Optional[float] = None
    fill_qty: Optional[float] = None
    fees: Optional[float] = None
    inventory: Optional[float] = None
    realized_pnl: Optional[float] = None
    
    # Additional context
    queue_position: Optional[float] = None
    ahead_volume: Optional[float] = None
    time_in_book_ms: Optional[int] = None
    
    # E1 additions for live summaries
    queue_wait_ms: Optional[float] = None
    price_bin_bps: Optional[int] = None


class ResearchRecorder:
    """Research data recorder with hourly file rotation and compression."""
    
    def __init__(self, ctx: AppConfig, data_dir: str = "./data/research",
                 summaries_dir: str = "data/research/summaries",
                 retention_days: Optional[int] = 14,
                 keep_last: Optional[int] = None,
                 overwrite_existing_hour: bool = True,
                 merge_strategy: Optional[str] = None,
                 bins_max_bps: int = 50,
                 percentiles_used: tuple = (0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99),
                 round_dp: int = 2,
                 lock_mode: Literal["none", "lockfile", "o_excl"] = "lockfile"):
        """Initialize research recorder with hardening features."""
        self.ctx = ctx
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # E1 hardening: Configure summaries behavior
        self.summaries_dir = Path(summaries_dir)
        self.summaries_dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.keep_last = keep_last
        self.overwrite_existing_hour = overwrite_existing_hour
        self.merge_strategy = merge_strategy
        self.bins_max_bps = bins_max_bps
        self.percentiles_used = percentiles_used
        self.round_dp = round_dp
        self.lock_mode = lock_mode
        
        # Buffers for batching
        self.market_buffer: List[ResearchRecord] = []
        self.event_buffer: List[ResearchRecord] = []
        
        # E1+: Live summary buffers per symbol and hour bucket
        # Structure: {symbol: {hour_bucket_str: {"orders": [], "quotes": [], ...}}}
        self.hourly_data: Dict[str, Dict[str, Dict]] = defaultdict(lambda: defaultdict(lambda: {
            "orders": [],
            "quotes": [],
            "fills": [],
            "queue_waits": []
        }))
        
        # File rotation - ensure UTC
        self.current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        self.current_file: Optional[Path] = None
        
        # Compression settings
        self.compress = getattr(ctx.storage, 'compress', 'zstd')
        self.buffer_size = getattr(ctx.storage, 'batch_size', 1000)
        self.flush_ms = getattr(ctx.storage, 'flush_ms', 200)
        
        # Background writer
        self._writer_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        
        # Statistics
        self.records_written = 0
        self.files_created = 0
        self.summaries_written = 0
        
        logger.info(f"Research recorder initialized: {data_dir}")
        logger.info(f"Summaries directory: {self.summaries_dir}")
        logger.info(f"Retention: {retention_days} days, keep_last: {keep_last}")
        logger.info(f"Lock mode: {lock_mode}")
    
    def _get_hour_bucket(self, event_ts_utc: Optional[datetime] = None) -> datetime:
        """Get hour bucket for event timestamping. Falls back to now_utc if event_ts_utc is None."""
        if event_ts_utc is not None:
            return event_ts_utc.replace(minute=0, second=0, microsecond=0)
        else:
            return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    
    def _hour_bucket_str(self, hour_bucket: datetime) -> str:
        """Convert hour bucket to string key."""
        return hour_bucket.strftime('%Y-%m-%d_%H')
    
    def _summary_path(self, symbol: str, hour_start_utc: datetime) -> Path:
        """Get path for hourly summary file."""
        filename = f"{symbol}_{hour_start_utc.strftime('%Y-%m-%d_%H')}.json"
        return self.summaries_dir / symbol / filename
    
    def _atomic_write_json(self, path: Path, obj: dict):
        """Write JSON file atomically with tmp -> fsync -> replace."""
        # Generate unique temporary filename
        random_hex = format(random.getrandbits(32), '08x')
        tmp_path = Path(f"{path}.tmp.{os.getpid()}.{random_hex}")
        
        try:
            # Ensure parent directory exists
            os.makedirs(path.parent, exist_ok=True)
            
            # Write to temporary file with rounding and sorting
            rounded_obj = round_floats(obj, self.round_dp)
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(rounded_obj, f, sort_keys=True, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # Atomic move
            os.replace(str(tmp_path), str(path))
            
            # Try to fsync directory (optional, not available everywhere)
            try:
                dirfd = os.open(path.parent, os.O_RDONLY)
                os.fsync(dirfd)
                os.close(dirfd)
            except (OSError, AttributeError):
                pass  # Not available on all platforms
                
        except Exception as e:
            # Clean up temp file on error
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            raise e
    
    def _parse_utc_from_filename(self, filename: str) -> Optional[datetime]:
        """Parse UTC datetime from summary filename."""
        try:
            # Extract YYYY-mm-dd_HH from filename like SYMBOL_YYYY-mm-dd_HH.json
            parts = filename.split('_')
            if len(parts) >= 3 and filename.endswith('.json'):
                # Get last two parts: date and hour
                date_part = parts[-2]  # YYYY-mm-dd
                hour_part = parts[-1].split('.')[0]  # HH (remove .json)
                
                timestamp_str = f"{date_part}T{hour_part}:00:00Z"
                return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except (ValueError, IndexError):
            pass
        return None
    
    def _safe_remove(self, file_path: Path):
        """Safely remove file with logging."""
        try:
            file_path.unlink()
            logger.debug(f"[E1] Removed file: {file_path}")
        except OSError as e:
            logger.warning(f"[E1] Failed to remove {file_path}: {e}")
    
    def _prune_summaries(self, symbol: str):
        """Remove old summary files based on retention policy."""
        symbol_dir = self.summaries_dir / symbol
        if not symbol_dir.is_dir():
            return
        
        # Get all JSON files
        json_files = [f for f in os.listdir(symbol_dir) if f.endswith('.json')]
        
        removed_count = 0
        
        # TTL pruning
        if self.retention_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
            for filename in json_files:
                ts = self._parse_utc_from_filename(filename)
                if ts and ts < cutoff:
                    self._safe_remove(symbol_dir / filename)
                    removed_count += 1
            
            # Refresh file list after TTL pruning
            json_files = [f for f in os.listdir(symbol_dir) if f.endswith('.json')]
        
        # keep_last pruning (takes priority over TTL)
        if self.keep_last is not None:
            # Sort files by modification time (newest first)
            file_paths = [(symbol_dir / f, f) for f in json_files]
            file_paths.sort(key=lambda x: x[0].stat().st_mtime, reverse=True)
            
            # Remove excess files
            to_remove = file_paths[self.keep_last:]
            for file_path, filename in to_remove:
                self._safe_remove(file_path)
                removed_count += 1
        
        if removed_count > 0:
            logger.info(f"[E1+] Pruned {removed_count} files for {symbol} (TTL/keep_last)")
            summaries_pruned_total.labels(symbol=symbol).inc(removed_count)
    
    async def _write_hour_summary_with_validation(self, symbol: str, hour_start_utc: datetime, summary: dict):
        """Write hourly summary with validation, locking, idempotency and merge support."""
        
        # Use locking to prevent concurrent writes (convert to sync context manager)
        with acquire_hour_lock(symbol, hour_start_utc, self.summaries_dir, self.lock_mode):
            path = self._summary_path(symbol, hour_start_utc)
            
            # Add E1+ hardening schema fields
            enhanced_summary = {
                "schema_version": "e1.1",  # E1+ uses e1.1
                "generated_at_utc": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                "window_utc": {
                    "hour_start": hour_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "hour_end": (hour_start_utc + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                "bins_max_bps": self.bins_max_bps,
                "percentiles_used": list(self.percentiles_used),
                **summary
            }
            
            # Validate enhanced payload
            is_valid, errors = validate_summary_payload(enhanced_summary)
            if not is_valid:
                error_msg = f"Summary validation failed for {symbol}:{hour_start_utc}: {errors}"
                logger.error(f"[E1+] {error_msg}")
                summary_write_errors_total.labels(symbol=symbol).inc()
                raise ValueError(error_msg)
            
            if path.exists():
                if self.overwrite_existing_hour:
                    logger.info(f"[E1+] Summary overwrite hour={hour_start_utc.isoformat()}Z")
                    self._atomic_write_json(path, enhanced_summary)
                elif self.merge_strategy == "sum_bins":
                    logger.info(f"[E1+] Summary merge hour={hour_start_utc.isoformat()}Z strategy=sum_bins")
                    
                    # Load and upgrade existing data
                    with open(path, 'r', encoding='utf-8') as f:
                        prev_summary = json.load(f)
                    prev_upgraded = upgrade_summary(prev_summary)
                    
                    # Merge counts
                    enhanced_summary["counts"]["orders"] += prev_upgraded.get("counts", {}).get("orders", 0)
                    enhanced_summary["counts"]["quotes"] += prev_upgraded.get("counts", {}).get("quotes", 0)
                    enhanced_summary["counts"]["fills"] += prev_upgraded.get("counts", {}).get("fills", 0)
                    
                    # Merge hit_rate_by_bin
                    prev_bins = prev_upgraded.get("hit_rate_by_bin", {})
                    for bin_key, prev_data in prev_bins.items():
                        current_data = enhanced_summary["hit_rate_by_bin"].setdefault(bin_key, {"count": 0, "fills": 0})
                        current_data["count"] += prev_data.get("count", 0)
                        current_data["fills"] += prev_data.get("fills", 0)
                    
                    # Keep new CDF (consider it "fresher")
                    self._atomic_write_json(path, enhanced_summary)
                else:
                    # No overwrite, no merge - leave as is
                    logger.debug(f"[E1+] Summary exists, skipping: {path}")
                    return
            else:
                self._atomic_write_json(path, enhanced_summary)
    
    async def start(self):
        """Start background writer task."""
        if self._writer_task is None:
            self._writer_task = asyncio.create_task(self._writer_loop())
            logger.info("Research recorder started")
    
    async def stop(self):
        """Stop recorder and flush remaining data."""
        self._stop_event.set()
        if self._writer_task:
            await self._writer_task
        await self._flush_all()
        logger.info("Research recorder stopped")
    
    def _calculate_price_bin_bps(self, quote_price: float, mid_price: float) -> int:
        """Calculate price bin in basis points from mid."""
        if mid_price <= 0:
            return 0
        
        diff_bps = abs(quote_price - mid_price) / mid_price * 10000
        # Cap at configured max bps
        return min(int(round(diff_bps)), self.bins_max_bps)
    
    def record_market_snapshot(self, symbol: str, orderbook: OrderBook, 
                             our_quotes: Dict[str, List[Dict]], vola_1m: float,
                             event_ts_utc: Optional[datetime] = None):
        """Record market snapshot with our quotes."""
        if not orderbook.bids or not orderbook.asks:
            return
        
        best_bid = float(orderbook.bids[0].price)
        best_ask = float(orderbook.asks[0].price)
        mid = float(orderbook.mid_price) if orderbook.mid_price else (best_bid + best_ask) / 2
        spread = (best_ask - best_bid) / mid * 10000  # in bps
        
        # Round to avoid floating point precision issues
        spread = round(spread, 2)
        
        # Calculate order book imbalance
        bid_vol = sum(float(level.size) for level in orderbook.bids[:5])
        ask_vol = sum(float(level.size) for level in orderbook.asks[:5])
        ob_imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0
        
        # Extract our quotes
        our_bids = our_quotes.get('bids', [])
        our_asks = our_quotes.get('asks', [])
        
        record = ResearchRecord(
            ts=orderbook.timestamp,
            symbol=symbol,
            mid=mid,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            vola_1m=vola_1m,
            ob_imbalance=ob_imbalance,
            our_bid_1=float(our_bids[0]['price']) if len(our_bids) > 0 else None,
            our_bid_1_size=float(our_bids[0]['size']) if len(our_bids) > 0 else None,
            our_bid_2=float(our_bids[1]['price']) if len(our_bids) > 1 else None,
            our_bid_2_size=float(our_bids[1]['size']) if len(our_bids) > 1 else None,
            our_bid_3=float(our_bids[2]['price']) if len(our_bids) > 2 else None,
            our_bid_3_size=float(our_bids[2]['size']) if len(our_bids) > 2 else None,
            our_ask_1=float(our_asks[0]['price']) if len(our_asks) > 0 else None,
            our_ask_1_size=float(our_asks[0]['size']) if len(our_asks) > 0 else None,
            our_ask_2=float(our_asks[1]['price']) if len(our_asks) > 1 else None,
            our_ask_2_size=float(our_asks[1]['size']) if len(our_asks) > 1 else None,
            our_ask_3=float(our_asks[2]['price']) if len(our_asks) > 2 else None,
            our_ask_3_size=float(our_asks[2]['size']) if len(our_asks) > 2 else None,
        )
        
        self.market_buffer.append(record)
        
        # E1+: Record quotes for hourly summary with event-time bucketing
        hour_bucket = self._get_hour_bucket(event_ts_utc or orderbook.timestamp)
        bucket_str = self._hour_bucket_str(hour_bucket)
        
        for quote in our_bids + our_asks:
            quote_price = float(quote['price'])
            price_bin_bps = self._calculate_price_bin_bps(quote_price, mid)
            
            self.hourly_data[symbol][bucket_str]["quotes"].append({
                "price_bin_bps": price_bin_bps,
                "timestamp": (event_ts_utc or orderbook.timestamp).isoformat()
            })
    
    def record_order_event(self, event_type: str, order: Order, 
                          fill_price: Optional[float] = None,
                          fill_qty: Optional[float] = None,
                          fees: Optional[float] = None,
                          inventory: Optional[float] = None,
                          realized_pnl: Optional[float] = None,
                          queue_position: Optional[float] = None,
                          ahead_volume: Optional[float] = None,
                          time_in_book_ms: Optional[int] = None,
                          queue_wait_ms: Optional[float] = None,
                          mid_price: Optional[float] = None,
                          event_ts_utc: Optional[datetime] = None):
        """Record order event (create/cancel/replace/fill)."""
        
        # Calculate price bin if we have mid price
        price_bin_bps = None
        if order.price and mid_price:
            price_bin_bps = self._calculate_price_bin_bps(float(order.price), mid_price)
        
        record = ResearchRecord(
            ts=event_ts_utc or datetime.now(timezone.utc),
            symbol=order.symbol,
            mid=mid_price,
            best_bid=None,  # Will be filled by market snapshot
            best_ask=None,
            spread=None,
            vola_1m=None,
            ob_imbalance=None,
            event_type=event_type,
            order_id=order.order_id,
            side=order.side.value,
            price=float(order.price) if order.price else None,
            qty=float(order.qty) if order.qty else None,
            fill_price=fill_price,
            fill_qty=fill_qty,
            fees=fees,
            inventory=inventory,
            realized_pnl=realized_pnl,
            queue_position=queue_position,
            ahead_volume=ahead_volume,
            time_in_book_ms=time_in_book_ms,
            queue_wait_ms=queue_wait_ms,
            price_bin_bps=price_bin_bps
        )
        
        self.event_buffer.append(record)
        
        # E1+: Collect data for hourly summaries with event-time bucketing
        hour_bucket = self._get_hour_bucket(event_ts_utc)
        bucket_str = self._hour_bucket_str(hour_bucket)
        
        if event_type == "create":
            self.hourly_data[order.symbol][bucket_str]["orders"].append({
                "price_bin_bps": price_bin_bps or 0,
                "timestamp": record.ts.isoformat()
            })
        elif event_type == "fill":
            self.hourly_data[order.symbol][bucket_str]["fills"].append({
                "price_bin_bps": price_bin_bps or 0,
                "timestamp": record.ts.isoformat()
            })
            
            # Record queue wait time for CDF calculation
            if queue_wait_ms is not None:
                self.hourly_data[order.symbol][bucket_str]["queue_waits"].append(queue_wait_ms)
    
    async def _writer_loop(self):
        """Background writer loop with file rotation."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self.flush_ms / 1000)
                await self._flush_and_rotate()
            except Exception as e:
                logger.error(f"Error in writer loop: {e}")
    
    async def _flush_and_rotate(self):
        """Flush buffers and rotate files if needed."""
        now = datetime.now(timezone.utc)
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        
        # Check if we need to rotate files
        if current_hour != self.current_hour:
            # E1: Generate hourly summaries before rotating
            await self._generate_hourly_summaries(self.current_hour)
            await self._rotate_file(current_hour)
        
        # Flush buffers
        await self._flush_buffers()
    
    async def _rotate_file(self, new_hour: datetime):
        """Rotate to new file for the hour."""
        if self.current_file and self.current_file.exists():
            # Compress the old file
            await self._compress_file(self.current_file)
        
        # Create new file
        filename = f"research_{new_hour.strftime('%Y%m%d_%H')}.parquet"
        self.current_file = self.data_dir / filename
        self.current_hour = new_hour
        self.files_created += 1
        
        logger.info(f"Rotated to new file: {self.current_file}")
    
    async def _flush_buffers(self):
        """Flush market and event buffers to current file."""
        if not self.current_file:
            return
        
        # Combine and sort records by timestamp
        all_records = self.market_buffer + self.event_buffer
        if not all_records:
            return
        
        # Sort by timestamp
        all_records.sort(key=lambda x: x.ts)
        
        # Convert to DataFrame
        df = pl.DataFrame([asdict(record) for record in all_records])
        
        # Write to file
        try:
            if self.current_file.exists():
                # Append to existing file
                existing_df = pl.read_parquet(self.current_file)
                combined_df = pl.concat([existing_df, df])
                combined_df.write_parquet(self.current_file)
            else:
                # Create new file
                df.write_parquet(self.current_file)
            
            self.records_written += len(all_records)
            
            # Clear buffers
            self.market_buffer.clear()
            self.event_buffer.clear()
            
        except Exception as e:
            logger.error(f"Error writing to {self.current_file}: {e}")
    
    async def _generate_hourly_summaries(self, hour: datetime):
        """Generate hourly summary files for all symbols and hour buckets."""
        if not self.hourly_data:
            return
        
        try:
            # Process all symbols and their hour buckets
            for symbol, hour_buckets in self.hourly_data.items():
                for bucket_str, data in hour_buckets.items():
                    # Parse hour bucket from string
                    bucket_hour = datetime.strptime(bucket_str, '%Y-%m-%d_%H').replace(tzinfo=timezone.utc)
                    
                    # Calculate hit rate by price bin
                    hit_rate_by_bin = {}
                    quote_count_by_bin = defaultdict(int)
                    fill_count_by_bin = defaultdict(int)
                    
                    # Count quotes by price bin
                    for quote in data["quotes"]:
                        bin_key = str(quote["price_bin_bps"])
                        quote_count_by_bin[bin_key] += 1
                    
                    # Count fills by price bin
                    for fill in data["fills"]:
                        bin_key = str(fill["price_bin_bps"])
                        fill_count_by_bin[bin_key] += 1
                    
                    # Calculate hit rates
                    for bin_bps in quote_count_by_bin:
                        count = quote_count_by_bin[bin_bps]
                        fills = fill_count_by_bin.get(bin_bps, 0)
                        hit_rate_by_bin[bin_bps] = {
                            "count": count,
                            "fills": fills
                        }
                    
                    # Calculate queue wait CDF using configured percentiles
                    queue_wait_cdf_ms = []
                    if data["queue_waits"]:
                        queue_waits = sorted(data["queue_waits"])
                        
                        for p in self.percentiles_used:
                            idx = min(int(p * len(queue_waits)), len(queue_waits) - 1)
                            queue_wait_cdf_ms.append({
                                "p": p,
                                "v": queue_waits[idx]  # Will be rounded by atomic_write_json
                            })
                    
                    # Build basic summary structure (will be enhanced in _write_hour_summary_with_validation)
                    summary = {
                        "symbol": symbol,
                        "hour_utc": bucket_hour.isoformat() + "Z",
                        "counts": {
                            "orders": len(data["orders"]),
                            "quotes": len(data["quotes"]),
                            "fills": len(data["fills"])
                        },
                        "hit_rate_by_bin": hit_rate_by_bin,
                        "queue_wait_cdf_ms": queue_wait_cdf_ms,
                        "metadata": {
                            "git_sha": get_git_sha(),
                            "cfg_hash": cfg_hash_sanitized(self.ctx)
                        }
                    }
                    
                    # Write using new atomic method with validation and locking
                    try:
                        await self._write_hour_summary_with_validation(symbol, bucket_hour, summary)
                        summaries_written_total.labels(symbol=symbol).inc()
                        self.summaries_written += 1
                        
                        # Prune old files
                        self._prune_summaries(symbol)
                        
                    except Exception as e:
                        logger.error(f"[E1+] Failed to write summary for {symbol}:{bucket_str}: {e}")
                        summary_write_errors_total.labels(symbol=symbol).inc()
            
            # Clear hourly data after writing
            self.hourly_data.clear()
            
        except Exception as e:
            logger.error(f"Error generating hourly summaries: {e}")
    

    
    async def _flush_all(self):
        """Flush all remaining data."""
        # Generate final hour summary before stopping
        if self.hourly_data:
            await self._generate_hourly_summaries(self.current_hour)
        
        await self._flush_buffers()
    
    async def _compress_file(self, file_path: Path):
        """Compress file using configured compression."""
        try:
            if self.compress == 'gzip':
                compressed_path = file_path.with_suffix('.parquet.gz')
                with open(file_path, 'rb') as f_in:
                    with gzip.open(compressed_path, 'wb') as f_out:
                        f_out.write(f_in.read())
                file_path.unlink()  # Remove original
                
            elif self.compress == 'zstd' and zstd is not None:
                compressed_path = file_path.with_suffix('.parquet.zst')
                with open(file_path, 'rb') as f_in:
                    with zstd.open(compressed_path, 'wb') as f_out:
                        f_out.write(f_in.read())
                file_path.unlink()  # Remove original
            elif self.compress == 'zstd':
                logger.warning("zstandard not available, skipping compression")
                return
            
            logger.info(f"Compressed {file_path} to {compressed_path}")
            
        except Exception as e:
            logger.error(f"Error compressing {file_path}: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get recorder statistics."""
        return {
            'records_written': self.records_written,
            'files_created': self.files_created,
            'summaries_written': self.summaries_written,
            'current_file': str(self.current_file) if self.current_file else None,
            'market_buffer_size': len(self.market_buffer),
            'event_buffer_size': len(self.event_buffer),
            'hourly_data_symbols': list(self.hourly_data.keys()),
            'compression': self.compress
        }

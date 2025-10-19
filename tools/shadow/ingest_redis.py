#!/usr/bin/env python3
"""
Redis Streams Ingest Adapter for Shadow Mode

Reads orderbook ticks from Redis Streams (Rust ingest), normalizes fields,
and implements seq-gap guard for monitoring sequence integrity.

Usage:
    from tools.shadow.ingest_redis import read_ticks_redis
    
    async for tick in read_ticks_redis(redis_url, stream, group, consumer):
        # Process tick
"""

import asyncio
import logging
import os
from typing import AsyncIterator, Dict, Optional

try:
    import redis.asyncio as aioredis
except ImportError:
    try:
        import aioredis
    except ImportError:
        aioredis = None

# Prometheus metrics (lazy import)
try:
    from prometheus_client import Counter, Gauge
    
    # Metrics
    shadow_seq_gaps_total = Counter(
        'shadow_seq_gaps_total',
        'Total sequence gaps detected in Redis stream',
        ['symbol']
    )
    
    shadow_ingest_lag_msgs = Gauge(
        'shadow_ingest_lag_msgs',
        'Lag in messages between stream and consumer',
        ['stream']
    )
except ImportError:
    shadow_seq_gaps_total = None
    shadow_ingest_lag_msgs = None

logger = logging.getLogger(__name__)


class SeqGapGuard:
    """
    Sequence gap detector for Redis stream messages.
    
    Tracks last sequence number per symbol and detects gaps/duplicates.
    """
    
    def __init__(self):
        self.last_seq: Dict[str, int] = {}
        self.gaps_detected: Dict[str, int] = {}
    
    def check(self, symbol: str, seq: int) -> Optional[str]:
        """
        Check sequence number for gaps.
        
        Args:
            symbol: Trading symbol
            seq: Current sequence number
        
        Returns:
            Error message if gap detected, None otherwise
        """
        if symbol not in self.last_seq:
            # First message for this symbol
            self.last_seq[symbol] = seq
            return None
        
        expected = self.last_seq[symbol] + 1
        
        if seq == expected:
            # Normal sequence
            self.last_seq[symbol] = seq
            return None
        
        elif seq > expected:
            # Gap detected
            gap_size = seq - expected
            self.gaps_detected[symbol] = self.gaps_detected.get(symbol, 0) + gap_size
            
            if shadow_seq_gaps_total:
                shadow_seq_gaps_total.labels(symbol=symbol).inc(gap_size)
            
            error = f"Seq gap: symbol={symbol}, expected={expected}, got={seq}, gap={gap_size}"
            logger.warning(error)
            
            self.last_seq[symbol] = seq
            return error
        
        else:
            # Duplicate or reordered (seq < expected)
            error = f"Seq out-of-order: symbol={symbol}, expected={expected}, got={seq}"
            logger.warning(error)
            
            # Don't update last_seq for duplicates
            return error
    
    def get_stats(self) -> Dict[str, int]:
        """Get gap statistics."""
        return dict(self.gaps_detected)


async def read_ticks_redis(
    redis_url: str,
    stream: str = "lob:ticks",
    group: str = "shadow",
    consumer_id: Optional[str] = None,
    batch_size: int = 100,
    block_ms: int = 1000,
) -> AsyncIterator[Dict]:
    """
    Read ticks from Redis Streams with seq-gap guard.
    
    Args:
        redis_url: Redis connection URL (e.g., redis://localhost:6379)
        stream: Stream name (default: lob:ticks)
        group: Consumer group name (default: shadow)
        consumer_id: Consumer ID (default: hostname-pid)
        batch_size: Messages per XREADGROUP call (default: 100)
        block_ms: Block timeout in ms (default: 1000)
    
    Yields:
        Normalized tick dicts with fields:
        - ts_server: Server timestamp (float)
        - seq: Sequence number (int)
        - symbol: Trading symbol (str)
        - bid: Best bid price (float)
        - bid_size: Best bid size (float)
        - ask: Best ask price (float)
        - ask_size: Best ask size (float)
        - last_qty: Last trade quantity (float)
    """
    if aioredis is None:
        raise ImportError("aioredis or redis.asyncio is required for Redis ingest")
    
    # Generate consumer ID if not provided
    if consumer_id is None:
        hostname = os.getenv("HOSTNAME", "shadow")
        pid = os.getpid()
        consumer_id = f"{hostname}-{pid}"
    
    logger.info(f"Connecting to Redis: {redis_url}")
    logger.info(f"Stream: {stream}, Group: {group}, Consumer: {consumer_id}")
    
    # Connect to Redis
    redis = await aioredis.from_url(redis_url, decode_responses=True)
    
    # Create consumer group if it doesn't exist
    try:
        await redis.xgroup_create(stream, group, id="0", mkstream=True)
        logger.info(f"Created consumer group: {group}")
    except Exception as e:
        # Group already exists (expected)
        if "BUSYGROUP" not in str(e):
            logger.warning(f"Failed to create group: {e}")
    
    # Initialize seq-gap guard
    seq_guard = SeqGapGuard()
    
    logger.info(f"Starting to read from stream: {stream}")
    
    try:
        while True:
            # Read batch from stream
            try:
                # XREADGROUP GROUP <group> <consumer> STREAMS <stream> >
                messages = await redis.xreadgroup(
                    groupname=group,
                    consumername=consumer_id,
                    streams={stream: ">"},
                    count=batch_size,
                    block=block_ms,
                )
                
                if not messages:
                    # No new messages, continue
                    await asyncio.sleep(0.01)
                    continue
                
                # Process messages
                for stream_name, stream_messages in messages:
                    for msg_id, fields in stream_messages:
                        try:
                            # Normalize tick from Redis message
                            tick = normalize_tick(fields)
                            
                            # Check sequence gap
                            symbol = tick.get("symbol", "UNKNOWN")
                            seq = tick.get("seq", 0)
                            
                            gap_error = seq_guard.check(symbol, seq)
                            if gap_error:
                                tick["_seq_gap_warning"] = gap_error
                            
                            # Yield normalized tick
                            yield tick
                            
                            # ACK message
                            await redis.xack(stream, group, msg_id)
                            
                        except Exception as e:
                            logger.error(f"Failed to process message {msg_id}: {e}")
                            # ACK anyway to prevent redelivery
                            await redis.xack(stream, group, msg_id)
                
            except asyncio.CancelledError:
                logger.info("Read loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error reading from stream: {e}")
                await asyncio.sleep(1.0)
    
    finally:
        logger.info(f"Closing Redis connection")
        await redis.close()


def normalize_tick(fields: Dict) -> Dict:
    """
    Normalize Redis message fields to standard tick format.
    
    Expected Redis message format (from Rust ingest):
    {
        "ts": "1234567890.123",      # Server timestamp
        "seq": "12345",               # Sequence number
        "symbol": "BTCUSDT",
        "bid": "50000.5",
        "bid_size": "1.23",
        "ask": "50001.0",
        "ask_size": "2.34",
        "last_qty": "0.05"
    }
    
    Args:
        fields: Raw Redis message fields
    
    Returns:
        Normalized tick dict
    """
    try:
        tick = {
            "ts_server": float(fields.get("ts", 0)),
            "seq": int(fields.get("seq", 0)),
            "symbol": fields.get("symbol", "UNKNOWN"),
            "bid": float(fields.get("bid", 0)),
            "bid_size": float(fields.get("bid_size", 0)),
            "ask": float(fields.get("ask", 0)),
            "ask_size": float(fields.get("ask_size", 0)),
            "last_qty": float(fields.get("last_qty", 0)),
        }
        
        # Add ingest timestamp
        import time
        tick["ts"] = time.time()
        
        return tick
    
    except (ValueError, TypeError) as e:
        logger.error(f"Failed to normalize tick: {e}, fields={fields}")
        raise


async def estimate_lag(redis_url: str, stream: str, group: str) -> int:
    """
    Estimate lag in messages for a consumer group.
    
    Args:
        redis_url: Redis connection URL
        stream: Stream name
        group: Consumer group name
    
    Returns:
        Estimated lag in messages (pending count)
    """
    if aioredis is None:
        return 0
    
    try:
        redis = await aioredis.from_url(redis_url, decode_responses=True)
        
        # Get pending messages count
        info = await redis.xpending(stream, group)
        
        await redis.close()
        
        # info format: (pending_count, min_id, max_id, consumers)
        if info and len(info) > 0:
            pending_count = info[0]
            
            if shadow_ingest_lag_msgs:
                shadow_ingest_lag_msgs.labels(stream=stream).set(pending_count)
            
            return pending_count
        
        return 0
    
    except Exception as e:
        logger.error(f"Failed to estimate lag: {e}")
        return 0


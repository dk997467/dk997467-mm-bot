#!/usr/bin/env python3
"""
Reordering Buffer for Shadow Mode Ingest

Buffers ticks by ts_server to handle out-of-order arrival,
implements backpressure (drop on overflow), and tracks reordering metrics.

Usage:
    buffer = ReorderBuffer(window_ms=40, max_size=4000)
    
    buffer.add(tick)  # Add tick to buffer
    
    for tick in buffer.flush():  # Get ordered ticks
        # Process tick
"""

import logging
import time
from collections import deque
from typing import Dict, List, Optional

# Prometheus metrics (lazy import)
try:
    from prometheus_client import Counter
    
    shadow_reordered_total = Counter(
        'shadow_reordered_total',
        'Total ticks reordered by timestamp',
        ['symbol']
    )
    
    shadow_backpressure_drops_total = Counter(
        'shadow_backpressure_drops_total',
        'Total ticks dropped due to backpressure',
        ['symbol']
    )
except ImportError:
    shadow_reordered_total = None
    shadow_backpressure_drops_total = None

logger = logging.getLogger(__name__)


class ReorderBuffer:
    """
    Time-based reordering buffer for market data ticks.
    
    Buffers incoming ticks and outputs them in ts_server order.
    Implements backpressure by dropping old ticks when buffer is full.
    """
    
    def __init__(
        self,
        window_ms: float = 40.0,
        max_size: int = 4000,
    ):
        """
        Initialize reordering buffer.
        
        Args:
            window_ms: Buffering window in milliseconds (default: 40)
            max_size: Maximum buffer size (default: 4000)
        """
        self.window_ms = window_ms
        self.max_size = max_size
        
        # Buffer storage (sorted by ts_server on flush)
        self.buffer: List[Dict] = []
        
        # Last emitted timestamp (for reordering detection)
        self.last_ts_server: Dict[str, float] = {}
        
        # Statistics
        self.reordered_count: Dict[str, int] = {}
        self.backpressure_drops: Dict[str, int] = {}
        self.total_added = 0
        self.total_flushed = 0
    
    def add(self, tick: Dict) -> None:
        """
        Add tick to buffer.
        
        Args:
            tick: Normalized tick with ts_server field
        """
        self.total_added += 1
        
        # Check buffer capacity (backpressure)
        if len(self.buffer) >= self.max_size:
            # Drop oldest tick (sorted by ts_server)
            symbol = tick.get("symbol", "UNKNOWN")
            
            self.backpressure_drops[symbol] = self.backpressure_drops.get(symbol, 0) + 1
            
            if shadow_backpressure_drops_total:
                shadow_backpressure_drops_total.labels(symbol=symbol).inc()
            
            # Drop oldest (sort buffer first)
            self.buffer.sort(key=lambda t: t.get("ts_server", 0))
            dropped = self.buffer.pop(0)
            
            logger.warning(
                f"Backpressure: dropped tick (symbol={dropped.get('symbol')}, "
                f"ts_server={dropped.get('ts_server'):.3f}, buffer_size={len(self.buffer)})"
            )
        
        # Add to buffer
        self.buffer.append(tick)
    
    def flush(self, force: bool = False) -> List[Dict]:
        """
        Flush ticks that are older than window_ms.
        
        Args:
            force: If True, flush all buffered ticks regardless of age
        
        Returns:
            List of ticks sorted by ts_server
        """
        if not self.buffer:
            return []
        
        current_time = time.time()
        window_sec = self.window_ms / 1000.0
        
        # Sort buffer by ts_server
        self.buffer.sort(key=lambda t: t.get("ts_server", 0))
        
        # Find cutoff (ticks older than window)
        cutoff_ts = current_time - window_sec
        
        output = []
        remaining = []
        
        for tick in self.buffer:
            ts_server = tick.get("ts_server", 0)
            
            if force or ts_server < cutoff_ts:
                # Tick is old enough to emit
                symbol = tick.get("symbol", "UNKNOWN")
                
                # Check if reordering happened
                last_ts = self.last_ts_server.get(symbol, 0)
                
                if ts_server < last_ts:
                    # Out-of-order (reordered)
                    self.reordered_count[symbol] = self.reordered_count.get(symbol, 0) + 1
                    
                    if shadow_reordered_total:
                        shadow_reordered_total.labels(symbol=symbol).inc()
                    
                    logger.debug(
                        f"Reordered tick: symbol={symbol}, "
                        f"ts_server={ts_server:.3f}, last_ts={last_ts:.3f}"
                    )
                
                # Update last emitted timestamp
                self.last_ts_server[symbol] = max(last_ts, ts_server)
                
                output.append(tick)
            else:
                # Tick is still within window
                remaining.append(tick)
        
        # Update buffer
        self.buffer = remaining
        self.total_flushed += len(output)
        
        return output
    
    def get_stats(self) -> Dict:
        """
        Get buffer statistics.
        
        Returns:
            Dict with buffer stats
        """
        return {
            "buffer_size": len(self.buffer),
            "total_added": self.total_added,
            "total_flushed": self.total_flushed,
            "reordered": dict(self.reordered_count),
            "backpressure_drops": dict(self.backpressure_drops),
        }
    
    def reset(self) -> None:
        """Reset buffer and statistics."""
        self.buffer.clear()
        self.last_ts_server.clear()
        self.reordered_count.clear()
        self.backpressure_drops.clear()
        self.total_added = 0
        self.total_flushed = 0


class ReorderBufferAsync:
    """
    Async wrapper for ReorderBuffer with automatic periodic flushing.
    
    Usage:
        async with ReorderBufferAsync(window_ms=40) as buffer:
            buffer.add(tick)
            async for tick in buffer:
                # Process ordered tick
    """
    
    def __init__(
        self,
        window_ms: float = 40.0,
        max_size: int = 4000,
        flush_interval_ms: float = 10.0,
    ):
        """
        Initialize async reordering buffer.
        
        Args:
            window_ms: Buffering window in milliseconds
            max_size: Maximum buffer size
            flush_interval_ms: Auto-flush interval in milliseconds
        """
        self.buffer = ReorderBuffer(window_ms=window_ms, max_size=max_size)
        self.flush_interval_ms = flush_interval_ms
        self._flush_task: Optional[object] = None
        self._output_queue: deque = deque()
    
    async def __aenter__(self):
        """Async context manager entry."""
        import asyncio
        
        # Start periodic flush task
        async def periodic_flush():
            while True:
                await asyncio.sleep(self.flush_interval_ms / 1000.0)
                flushed = self.buffer.flush()
                self._output_queue.extend(flushed)
        
        self._flush_task = asyncio.create_task(periodic_flush())
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except:
                pass
        
        # Final flush
        flushed = self.buffer.flush(force=True)
        self._output_queue.extend(flushed)
    
    def add(self, tick: Dict) -> None:
        """Add tick to buffer (sync)."""
        self.buffer.add(tick)
    
    async def get(self) -> Optional[Dict]:
        """
        Get next ordered tick (async).
        
        Returns:
            Next tick or None if queue empty
        """
        import asyncio
        
        # Wait for queue to have items
        while not self._output_queue:
            await asyncio.sleep(0.001)
        
        return self._output_queue.popleft() if self._output_queue else None
    
    def __aiter__(self):
        """Async iterator."""
        return self
    
    async def __anext__(self):
        """Async iterator next."""
        tick = await self.get()
        if tick is None:
            raise StopAsyncIteration
        return tick
    
    def get_stats(self) -> Dict:
        """Get buffer statistics."""
        return self.buffer.get_stats()





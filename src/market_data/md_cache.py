"""
Market Data Cache with TTL + Stale-While-Refresh.

Features:
- TTL-based caching (50-150ms typical)
- Stale-while-refresh: return stale data, async refresh in background
- Invalidation hooks: WS gap, bid/ask jumps
- Backpressure: max 1 inflight refresh per symbol
- Metrics: hit/miss ratio, cache age, refresh latency
"""
import asyncio
import time
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict
import logging

from src.common.config import MDCacheConfig

logger = logging.getLogger(__name__)


@dataclass
class MDCacheEntry:
    """Market data cache entry."""
    symbol: str
    orderbook: Dict[str, Any]  # Raw orderbook snapshot
    timestamp_ms: int  # When cached
    depth: int  # Orderbook depth
    update_id: Optional[int] = None  # WS update sequence/ID
    
    def age_ms(self) -> int:
        """Get age in milliseconds."""
        return int(time.time() * 1000) - self.timestamp_ms
    
    def is_stale(self, ttl_ms: int) -> bool:
        """Check if entry is stale (age > TTL)."""
        return self.age_ms() > ttl_ms
    
    def is_fresh_for_pricing(self, fresh_ms: int) -> bool:
        """Check if fresh enough for pricing decisions."""
        return self.age_ms() <= fresh_ms


class MDCache:
    """
    Market data cache with stale-while-refresh.
    
    Optimizes fetch_md latency by caching orderbook snapshots.
    """
    
    def __init__(
        self,
        config: MDCacheConfig,
        refresh_callback: Optional[callable] = None
    ):
        """
        Initialize MD cache.
        
        Args:
            config: Cache configuration
            refresh_callback: Async function to refresh orderbook
                              Signature: async def refresh(symbol, depth) -> orderbook
        """
        self.config = config
        self.refresh_callback = refresh_callback
        
        # Cache storage: symbol -> MDCacheEntry
        self._cache: Dict[str, MDCacheEntry] = {}
        
        # Inflight refresh tracking: symbol -> asyncio.Task
        self._inflight_refreshes: Dict[str, asyncio.Task] = {}
        
        # Metrics
        self._hit_count: Dict[str, int] = defaultdict(int)
        self._miss_count: Dict[str, int] = defaultdict(int)
        self._refresh_latencies: Dict[str, list] = defaultdict(list)
        
        # Lock for thread-safe operations (HIGH PRIORITY FIX)
        self._lock = asyncio.Lock()
        self._lock_contention_count = 0
        self._lock_wait_times_ms: list = []
        
        logger.info(
            f"[MD_CACHE] Initialized: enabled={config.enabled}, "
            f"ttl_ms={config.ttl_ms}, stale_ok={config.stale_ok}"
        )
    
    async def get_orderbook(
        self,
        symbol: str,
        depth: int = 50,
        max_age_ms: Optional[int] = None,
        fresh_only: bool = False,
        expected_update_id: Optional[int] = None,
        use_case: str = "general"
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """
        Get orderbook from cache or refresh.
        
        Args:
            symbol: Trading symbol
            depth: Orderbook depth
            max_age_ms: Max age override (default: config.ttl_ms)
            fresh_only: Force fresh data only (for guards/halts)
            expected_update_id: Expected WS update ID (for sequence validation)
            use_case: Use case tag ("general", "pricing", "guards")
        
        Returns:
            (orderbook_snapshot, metadata)
            metadata: {"cache_hit": bool, "age_ms": int, "used_stale": bool, 
                      "depth_miss": bool, "sequence_gap": bool}
        """
        metadata = {
            "cache_hit": False,
            "age_ms": 0,
            "used_stale": False,
            "depth_miss": False,
            "sequence_gap": False
        }
        
        if not self.config.enabled:
            # Cache disabled - always miss
            return None, metadata
        
        ttl = max_age_ms if max_age_ms is not None else self.config.ttl_ms
        
        # Acquire lock for cache access (protected read)
        lock_start = time.monotonic_ns()
        was_locked = self._lock.locked()
        
        async with self._lock:
            # Track lock contention metrics
            if was_locked:
                self._lock_contention_count += 1
            lock_wait_ms = (time.monotonic_ns() - lock_start) / 1_000_000
            self._lock_wait_times_ms.append(lock_wait_ms)
            
            # Check cache (critical section)
            entry = self._cache.get(symbol) if symbol in self._cache else None
        
        # Process entry outside lock (no shared state access)
        if entry:
            metadata["age_ms"] = entry.age_ms()
            
            # Check depth consistency - no upscaling
            if entry.depth < depth:
                metadata["depth_miss"] = True
                self._miss_count[symbol] += 1
                logger.debug(
                    f"[MD_CACHE] DEPTH_MISS {symbol} have={entry.depth} need={depth}"
                )
                # Force refresh with correct depth
                if self.refresh_callback:
                    orderbook = await self._refresh_with_metrics(symbol, depth)
                    return orderbook, metadata
                return None, metadata
            
            # Check sequence/update_id gap
            if expected_update_id is not None and entry.update_id is not None:
                if expected_update_id > entry.update_id + 1:
                    # Sequence gap detected
                    metadata["sequence_gap"] = True
                    self._miss_count[symbol] += 1
                    logger.warning(
                        f"[MD_CACHE] SEQUENCE_GAP {symbol} expected={expected_update_id} "
                        f"cached={entry.update_id}, forcing refresh"
                    )
                    # Force refresh
                    if self.refresh_callback:
                        orderbook = await self._refresh_with_metrics(symbol, depth, expected_update_id)
                        return orderbook, metadata
                    return None, metadata
                
                elif expected_update_id < entry.update_id:
                    # Rewind detected - invalidate
                    logger.warning(
                        f"[MD_CACHE] REWIND {symbol} expected={expected_update_id} "
                        f"cached={entry.update_id}, invalidating"
                    )
                    self.invalidate(symbol, reason="rewind")
                    self._miss_count[symbol] += 1
                    if self.refresh_callback:
                        orderbook = await self._refresh_with_metrics(symbol, depth, expected_update_id)
                        return orderbook, metadata
                    return None, metadata
            
            # Fresh data
            if not entry.is_stale(ttl):
                # Cache hit - fresh data
                self._hit_count[symbol] += 1
                metadata["cache_hit"] = True
                logger.debug(
                    f"[MD_CACHE] HIT {symbol} age={entry.age_ms()}ms (< {ttl}ms)"
                )
                return entry.orderbook, metadata
            
            # Stale data
            if fresh_only:
                # Guards/halts: fresh_only mode - force synchronous refresh
                self._miss_count[symbol] += 1
                logger.warning(
                    f"[MD_CACHE] FRESH_ONLY {symbol} age={entry.age_ms()}ms, "
                    f"forcing synchronous refresh (use_case={use_case})"
                )
                if self.refresh_callback:
                    try:
                        orderbook = await asyncio.wait_for(
                            self._refresh_with_metrics(symbol, depth, expected_update_id),
                            timeout=0.05  # 50ms timeout
                        )
                        return orderbook, metadata
                    except asyncio.TimeoutError:
                        logger.error(
                            f"[MD_CACHE] FRESH_ONLY timeout for {symbol}, "
                            f"returning stale as last resort"
                        )
                        metadata["used_stale"] = True
                        return entry.orderbook, metadata
                return None, metadata
            
            # Pricing use case: check fresh_ms_for_pricing threshold
            if use_case == "pricing" and not entry.is_fresh_for_pricing(self.config.fresh_ms_for_pricing):
                # Stale for pricing - trigger refresh
                self._miss_count[symbol] += 1
                metadata["used_stale"] = True
                logger.info(
                    f"[MD_CACHE] PRICING_STALE {symbol} age={entry.age_ms()}ms "
                    f"(> {self.config.fresh_ms_for_pricing}ms), triggering refresh"
                )
                # Trigger async refresh (non-blocking)
                self._trigger_refresh_async(symbol, depth, expected_update_id)
                # Return stale (will be marked for safety widening)
                return entry.orderbook, metadata
            
            # General stale-while-refresh
            if self.config.stale_ok:
                self._miss_count[symbol] += 1
                metadata["used_stale"] = True
                logger.debug(
                    f"[MD_CACHE] STALE {symbol} age={entry.age_ms()}ms (> {ttl}ms), "
                    f"returning stale + triggering refresh"
                )
                # Trigger async refresh (non-blocking)
                self._trigger_refresh_async(symbol, depth, expected_update_id)
                # Return stale data immediately
                return entry.orderbook, metadata
        
        # Cache miss or stale not allowed - must refresh synchronously
        self._miss_count[symbol] += 1
        logger.debug(f"[MD_CACHE] MISS {symbol}, refreshing synchronously")
        
        if self.refresh_callback:
            orderbook = await self._refresh_with_metrics(symbol, depth, expected_update_id)
            return orderbook, metadata
        
        return None, metadata
    
    def _trigger_refresh_async(self, symbol: str, depth: int, expected_update_id: Optional[int] = None):
        """
        Trigger async refresh (non-blocking, thread-safe).
        
        Args:
            symbol: Trading symbol
            depth: Orderbook depth
            expected_update_id: Expected WS update ID
        """
        # NOTE: This is a sync method but needs to check async state
        # In practice, it's called from async context, so we can't use async with here
        # We'll use try_acquire pattern or accept potential race (acceptable for refresh triggers)
        
        # Check if already refreshing (backpressure) - best-effort check
        if symbol in self._inflight_refreshes:
            task = self._inflight_refreshes[symbol]
            if not task.done():
                logger.debug(f"[MD_CACHE] Refresh already in progress for {symbol}, skipping")
                return
        
        # Create background task
        task = asyncio.create_task(self._refresh_with_metrics(symbol, depth, expected_update_id))
        self._inflight_refreshes[symbol] = task
        
        # Cleanup on completion
        task.add_done_callback(lambda t: self._cleanup_refresh_task(symbol))
    
    def _cleanup_refresh_task(self, symbol: str):
        """Cleanup completed refresh task."""
        if symbol in self._inflight_refreshes:
            del self._inflight_refreshes[symbol]
    
    async def _refresh_with_metrics(
        self, 
        symbol: str, 
        depth: int,
        expected_update_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Refresh orderbook and update cache with metrics tracking.
        
        Args:
            symbol: Trading symbol
            depth: Orderbook depth
            expected_update_id: Expected WS update ID
        
        Returns:
            Fresh orderbook snapshot
        """
        if not self.refresh_callback:
            logger.warning(f"[MD_CACHE] No refresh callback configured")
            return None
        
        start_ns = time.monotonic_ns()
        
        try:
            # Call refresh callback
            orderbook = await self.refresh_callback(symbol, depth)
            
            # Track latency
            latency_ms = (time.monotonic_ns() - start_ns) / 1_000_000
            self._refresh_latencies[symbol].append(latency_ms)
            
            # Update cache (protected write)
            if orderbook:
                # Extract update_id if available
                update_id = orderbook.get("update_id") or expected_update_id
                async with self._lock:
                    self._update_cache(symbol, orderbook, depth, update_id)
                logger.debug(
                    f"[MD_CACHE] Refreshed {symbol} in {latency_ms:.2f}ms "
                    f"update_id={update_id}"
                )
            
            return orderbook
        
        except Exception as e:
            latency_ms = (time.monotonic_ns() - start_ns) / 1_000_000
            logger.error(
                f"[MD_CACHE] Refresh failed for {symbol}: {e} "
                f"(took {latency_ms:.2f}ms)"
            )
            return None
    
    def _update_cache(
        self, 
        symbol: str, 
        orderbook: Dict[str, Any], 
        depth: int,
        update_id: Optional[int] = None
    ):
        """
        Update cache entry (thread-safe).
        
        Args:
            symbol: Trading symbol
            orderbook: Fresh orderbook snapshot
            depth: Orderbook depth
            update_id: WS update sequence/ID
        """
        entry = MDCacheEntry(
            symbol=symbol,
            orderbook=orderbook,
            timestamp_ms=int(time.time() * 1000),
            depth=depth,
            update_id=update_id
        )
        
        # This method is called from _refresh_with_metrics which is already async
        # We'll make it sync but call it in async context with run_in_executor if needed
        # For now, we'll document that this must be called within lock context
        self._cache[symbol] = entry
        
        logger.debug(f"[MD_CACHE] Updated {symbol}, age=0ms, update_id={update_id}")
    
    def invalidate(self, symbol: str, reason: str = "manual"):
        """
        Invalidate cache entry.
        
        Args:
            symbol: Trading symbol
            reason: Invalidation reason
        """
        if symbol in self._cache:
            del self._cache[symbol]
            logger.info(f"[MD_CACHE] Invalidated {symbol}, reason={reason}")
    
    def invalidate_all(self, reason: str = "manual"):
        """
        Invalidate all cache entries.
        
        Args:
            reason: Invalidation reason
        """
        count = len(self._cache)
        self._cache.clear()
        logger.info(f"[MD_CACHE] Invalidated all {count} entries, reason={reason}")
    
    def get_hit_ratio(self, symbol: Optional[str] = None) -> float:
        """
        Get cache hit ratio.
        
        Args:
            symbol: Optional symbol (None = global)
        
        Returns:
            Hit ratio [0.0, 1.0]
        """
        if symbol:
            hits = self._hit_count[symbol]
            misses = self._miss_count[symbol]
        else:
            hits = sum(self._hit_count.values())
            misses = sum(self._miss_count.values())
        
        total = hits + misses
        return hits / total if total > 0 else 0.0
    
    def get_cache_age_ms(self, symbol: str) -> Optional[int]:
        """
        Get current cache age for symbol.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Age in ms or None if not cached
        """
        entry = self._cache.get(symbol)
        return entry.age_ms() if entry else None
    
    def get_refresh_latency_p95(self, symbol: Optional[str] = None) -> float:
        """
        Get p95 refresh latency.
        
        Args:
            symbol: Optional symbol (None = global)
        
        Returns:
            p95 latency in ms
        """
        if symbol:
            latencies = self._refresh_latencies.get(symbol, [])
        else:
            latencies = []
            for symbol_latencies in self._refresh_latencies.values():
                latencies.extend(symbol_latencies)
        
        if not latencies:
            return 0.0
        
        sorted_latencies = sorted(latencies)
        p95_idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[p95_idx] if p95_idx < len(sorted_latencies) else sorted_latencies[-1]
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get metrics summary.
        
        Returns:
            Metrics dict with hit_ratio, cache_sizes, lock_contention, etc.
        """
        # Calculate lock contention metrics
        lock_contention_rate = 0.0
        lock_wait_p95_ms = 0.0
        
        if self._lock_wait_times_ms:
            total_accesses = len(self._lock_wait_times_ms)
            lock_contention_rate = self._lock_contention_count / total_accesses if total_accesses > 0 else 0.0
            
            sorted_waits = sorted(self._lock_wait_times_ms)
            p95_idx = int(len(sorted_waits) * 0.95)
            lock_wait_p95_ms = sorted_waits[p95_idx] if p95_idx < len(sorted_waits) else sorted_waits[-1]
        
        return {
            "enabled": self.config.enabled,
            "hit_ratio_global": round(self.get_hit_ratio(), 4),
            "cache_size": len(self._cache),
            "inflight_refreshes": len(self._inflight_refreshes),
            "total_hits": sum(self._hit_count.values()),
            "total_misses": sum(self._miss_count.values()),
            "refresh_latency_p95_ms": round(self.get_refresh_latency_p95(), 2),
            "lock_contention_rate": round(lock_contention_rate, 4),
            "lock_wait_p95_ms": round(lock_wait_p95_ms, 4),
            "lock_contention_count": self._lock_contention_count,
            "symbols_cached": list(self._cache.keys()),
            "per_symbol_hit_ratio": {
                symbol: round(self.get_hit_ratio(symbol), 4)
                for symbol in set(list(self._hit_count.keys()) + list(self._miss_count.keys()))
            }
        }


class MDCacheInvalidator:
    """
    Monitors for invalidation triggers.
    
    - WS gap > threshold
    - Bid/ask jump > X ticks
    """
    
    def __init__(self, cache: MDCache, config: MDCacheConfig):
        """
        Initialize invalidator.
        
        Args:
            cache: MD cache instance
            config: Cache configuration
        """
        self.cache = cache
        self.config = config
        
        # Track last bid/ask for jump detection
        self._last_bid: Dict[str, float] = {}
        self._last_ask: Dict[str, float] = {}
    
    def check_ws_gap(self, ws_gap_ms: int):
        """
        Check if WS gap exceeds threshold and invalidate if needed.
        
        Args:
            ws_gap_ms: WebSocket gap in milliseconds
        """
        if ws_gap_ms > self.config.invalidate_on_ws_gap_ms:
            logger.warning(
                f"[MD_CACHE] WS gap {ws_gap_ms}ms > {self.config.invalidate_on_ws_gap_ms}ms, "
                f"invalidating all cache"
            )
            self.cache.invalidate_all(reason=f"ws_gap_{ws_gap_ms}ms")
    
    def check_price_jump(
        self,
        symbol: str,
        current_bid: float,
        current_ask: float,
        max_jump_ticks: int = 5
    ):
        """
        Check if bid/ask jumped more than threshold and invalidate if needed.
        
        Args:
            symbol: Trading symbol
            current_bid: Current best bid
            current_ask: Current best ask
            max_jump_ticks: Max allowed jump in ticks
        """
        if symbol not in self._last_bid or symbol not in self._last_ask:
            # First observation - just record
            self._last_bid[symbol] = current_bid
            self._last_ask[symbol] = current_ask
            return
        
        last_bid = self._last_bid[symbol]
        last_ask = self._last_ask[symbol]
        
        # Assume tick size is 0.1% of price (simplified)
        tick_size = current_bid * 0.001
        
        bid_jump_ticks = abs(current_bid - last_bid) / tick_size
        ask_jump_ticks = abs(current_ask - last_ask) / tick_size
        
        if bid_jump_ticks > max_jump_ticks or ask_jump_ticks > max_jump_ticks:
            logger.warning(
                f"[MD_CACHE] Price jump detected for {symbol}: "
                f"bid_jump={bid_jump_ticks:.1f} ticks, ask_jump={ask_jump_ticks:.1f} ticks, "
                f"invalidating cache"
            )
            self.cache.invalidate(symbol, reason=f"price_jump_{max(bid_jump_ticks, ask_jump_ticks):.1f}ticks")
        
        # Update last prices
        self._last_bid[symbol] = current_bid
        self._last_ask[symbol] = current_ask


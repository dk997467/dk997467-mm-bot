"""
Unit tests for MD cache.

Tests:
- Cache hit/miss
- TTL expiration
- Stale-while-refresh
- Invalidation hooks
- Backpressure (max inflight refresh)
"""
import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock

from src.market_data.md_cache import MDCache, MDCacheEntry, MDCacheInvalidator
from src.common.config import MDCacheConfig


class TestMDCacheEntry:
    """Test MD cache entry."""
    
    def test_entry_age(self):
        """Test entry age calculation."""
        entry = MDCacheEntry(
            symbol="BTCUSDT",
            orderbook={"bids": [], "asks": []},
            timestamp_ms=int((time.time() - 0.05) * 1000),  # 50ms ago
            depth=50
        )
        
        age = entry.age_ms()
        assert 45 <= age <= 55  # ~50ms (allow jitter)
    
    def test_entry_is_stale(self):
        """Test stale detection."""
        entry = MDCacheEntry(
            symbol="BTCUSDT",
            orderbook={"bids": [], "asks": []},
            timestamp_ms=int((time.time() - 0.15) * 1000),  # 150ms ago
            depth=50
        )
        
        assert entry.is_stale(100)  # 150ms > 100ms TTL
        assert not entry.is_stale(200)  # 150ms < 200ms TTL


class TestMDCache:
    """Test MD cache core functionality."""
    
    @pytest.fixture
    def config(self):
        """Create test config."""
        return MDCacheConfig(
            enabled=True,
            ttl_ms=100,
            max_depth=50,
            stale_ok=True,
            invalidate_on_ws_gap_ms=300,
            max_inflight_refresh=1
        )
    
    @pytest.fixture
    def mock_refresh(self):
        """Create mock refresh callback."""
        async def refresh(symbol: str, depth: int):
            # Simulate latency
            await asyncio.sleep(0.01)
            return {
                "symbol": symbol,
                "bids": [[50000.0, 1.0]],
                "asks": [[50001.0, 1.0]]
            }
        
        return refresh
    
    @pytest.mark.asyncio
    async def test_cache_disabled(self, config):
        """Cache disabled should always miss."""
        config.enabled = False
        cache = MDCache(config)
        
        result, meta = await cache.get_orderbook("BTCUSDT", depth=50)
        assert result is None
        assert meta["cache_hit"] is False
    
    @pytest.mark.asyncio
    async def test_cache_miss_first_call(self, config, mock_refresh):
        """First call should miss and refresh."""
        cache = MDCache(config, refresh_callback=mock_refresh)
        
        result, meta = await cache.get_orderbook("BTCUSDT", depth=50)
        
        assert result is not None
        assert result["symbol"] == "BTCUSDT"
        assert meta["cache_hit"] is False
        assert cache.get_hit_ratio("BTCUSDT") == 0.0  # First call = miss
    
    @pytest.mark.asyncio
    async def test_cache_hit_within_ttl(self, config, mock_refresh):
        """Second call within TTL should hit."""
        cache = MDCache(config, refresh_callback=mock_refresh)
        
        # First call - miss
        result1, meta1 = await cache.get_orderbook("BTCUSDT", depth=50)
        assert result1 is not None
        assert meta1["cache_hit"] is False
        
        # Second call immediately - should hit
        result2, meta2 = await cache.get_orderbook("BTCUSDT", depth=50)
        assert result2 is not None
        assert meta2["cache_hit"] is True
        assert result2 == result1  # Same data
        
        # Hit ratio should be 50% (1 hit, 1 miss)
        assert cache.get_hit_ratio("BTCUSDT") == 0.5
    
    @pytest.mark.asyncio
    async def test_cache_stale_while_refresh(self, config, mock_refresh):
        """Stale data should be returned while refreshing."""
        config.ttl_ms = 50  # Short TTL
        cache = MDCache(config, refresh_callback=mock_refresh)
        
        # First call - populate cache
        result1, meta1 = await cache.get_orderbook("BTCUSDT", depth=50)
        assert result1 is not None
        assert meta1["cache_hit"] is False
        
        # Wait for TTL to expire
        await asyncio.sleep(0.06)
        
        # Second call - should return stale + trigger refresh
        result2, meta2 = await cache.get_orderbook("BTCUSDT", depth=50)
        assert result2 is not None
        assert meta2["used_stale"] is True
        assert result2 == result1  # Stale data returned immediately
        
        # Wait for background refresh to complete
        await asyncio.sleep(0.02)
        
        # Third call - should hit fresh cache
        result3, meta3 = await cache.get_orderbook("BTCUSDT", depth=50)
        assert result3 is not None
        assert meta3["cache_hit"] is True
    
    def test_cache_invalidate(self, config):
        """Test cache invalidation."""
        cache = MDCache(config)
        
        # Manually add entry
        cache._update_cache("BTCUSDT", {"bids": [], "asks": []}, 50)
        assert "BTCUSDT" in cache._cache
        
        # Invalidate
        cache.invalidate("BTCUSDT", reason="test")
        assert "BTCUSDT" not in cache._cache
    
    def test_cache_invalidate_all(self, config):
        """Test invalidate all."""
        cache = MDCache(config)
        
        # Add multiple entries
        cache._update_cache("BTCUSDT", {"bids": [], "asks": []}, 50)
        cache._update_cache("ETHUSDT", {"bids": [], "asks": []}, 50)
        assert len(cache._cache) == 2
        
        # Invalidate all
        cache.invalidate_all(reason="test")
        assert len(cache._cache) == 0
    
    def test_cache_metrics_summary(self, config):
        """Test metrics summary."""
        cache = MDCache(config)
        
        # Populate some metrics
        cache._hit_count["BTCUSDT"] = 10
        cache._miss_count["BTCUSDT"] = 5
        cache._refresh_latencies["BTCUSDT"] = [10.0, 20.0, 30.0]
        
        summary = cache.get_metrics_summary()
        
        assert summary["enabled"] is True
        assert summary["total_hits"] == 10
        assert summary["total_misses"] == 5
        assert summary["hit_ratio_global"] > 0.0


class TestMDCacheInvalidator:
    """Test cache invalidator."""
    
    @pytest.fixture
    def config(self):
        """Create test config."""
        return MDCacheConfig(
            enabled=True,
            ttl_ms=100,
            invalidate_on_ws_gap_ms=300
        )
    
    @pytest.fixture
    def cache(self, config):
        """Create cache instance."""
        return MDCache(config)
    
    def test_ws_gap_invalidation(self, config, cache):
        """Test WS gap invalidation."""
        invalidator = MDCacheInvalidator(cache, config)
        
        # Add cache entry
        cache._update_cache("BTCUSDT", {"bids": [], "asks": []}, 50)
        assert len(cache._cache) == 1
        
        # Large WS gap
        invalidator.check_ws_gap(ws_gap_ms=500)
        
        # Cache should be invalidated
        assert len(cache._cache) == 0
    
    def test_price_jump_invalidation(self, config, cache):
        """Test price jump invalidation."""
        invalidator = MDCacheInvalidator(cache, config)
        
        # Add cache entry
        cache._update_cache("BTCUSDT", {"bids": [], "asks": []}, 50)
        
        # First observation - no invalidation
        invalidator.check_price_jump("BTCUSDT", 50000.0, 50001.0)
        assert "BTCUSDT" in cache._cache
        
        # Small jump - no invalidation
        invalidator.check_price_jump("BTCUSDT", 50005.0, 50006.0)
        assert "BTCUSDT" in cache._cache
        
        # Large jump - should invalidate
        invalidator.check_price_jump("BTCUSDT", 51000.0, 51001.0, max_jump_ticks=5)
        assert "BTCUSDT" not in cache._cache


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


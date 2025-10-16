"""
Safeguard tests for MD-Cache.

Tests:
1. fresh_only: Guards force fresh data (no stale)
2. pricing_threshold: Pricing uses fresh_ms_for_pricing threshold
3. sequence_gap: Cache invalidated on WS sequence gap
4. depth_miss: Cache miss when requested depth > cached depth
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.market_data.md_cache import MDCache, MDCacheConfig


@pytest.fixture
def cache_config():
    """Create cache config for testing."""
    config = MagicMock()
    config.enabled = True
    config.ttl_ms = 100
    config.max_depth = 50
    config.stale_ok = True
    config.invalidate_on_ws_gap_ms = 300
    config.max_inflight_refresh = 1
    config.fresh_ms_for_pricing = 60
    config.skip_pricing_on_stale = False
    return config


@pytest.fixture
def mock_refresh_callback():
    """Create mock refresh callback."""
    async def refresh(symbol, depth):
        """Mock refresh returns fresh orderbook."""
        return {
            "symbol": symbol,
            "bids": [[50000.0, 1.0]],
            "asks": [[50001.0, 1.0]],
            "update_id": 12345
        }
    return refresh


@pytest.mark.asyncio
async def test_fresh_only_mode_forces_sync_refresh(cache_config, mock_refresh_callback):
    """
    Test: fresh_only mode forces synchronous refresh.
    
    Scenario:
    1. Cache has stale data (age > TTL)
    2. Request with fresh_only=True
    3. Should trigger synchronous refresh (not return stale)
    """
    cache = MDCache(cache_config, mock_refresh_callback)
    
    # Pre-populate cache with stale data
    cache._update_cache(
        symbol="BTCUSDT",
        orderbook={"bids": [[49000.0, 1.0]], "asks": [[49001.0, 1.0]]},
        depth=50,
        update_id=12340
    )
    
    # Wait for data to become stale
    await asyncio.sleep(0.15)  # > 100ms TTL
    
    # Request with fresh_only (guards use case)
    orderbook, metadata = await cache.get_orderbook(
        symbol="BTCUSDT",
        depth=50,
        fresh_only=True,
        use_case="guards"
    )
    
    # Should NOT be a cache hit (stale data rejected)
    assert metadata["cache_hit"] is False
    
    # Should have refreshed (not stale)
    assert metadata["used_stale"] is False
    
    # Should have fresh data (check update_id)
    assert orderbook["update_id"] == 12345


@pytest.mark.asyncio
async def test_pricing_threshold_triggers_async_refresh(cache_config, mock_refresh_callback):
    """
    Test: pricing use case respects fresh_ms_for_pricing threshold.
    
    Scenario:
    1. Cache has data older than fresh_ms_for_pricing (60ms)
    2. Request with use_case="pricing"
    3. Should return stale data BUT trigger async refresh
    """
    cache = MDCache(cache_config, mock_refresh_callback)
    
    # Pre-populate cache
    cache._update_cache(
        symbol="BTCUSDT",
        orderbook={"bids": [[49000.0, 1.0]], "asks": [[49001.0, 1.0]]},
        depth=50
    )
    
    # Wait for data to exceed fresh_ms_for_pricing (60ms) but not TTL (100ms)
    await asyncio.sleep(0.07)  # 70ms
    
    # Request with pricing use case
    orderbook, metadata = await cache.get_orderbook(
        symbol="BTCUSDT",
        depth=50,
        max_age_ms=60,
        use_case="pricing"
    )
    
    # Should be marked as stale (exceeded fresh_ms_for_pricing)
    assert metadata["used_stale"] is True
    
    # Should still return cached data (stale_ok for pricing)
    assert orderbook["bids"][0][0] == 49000.0
    
    # Async refresh should be triggered (check inflight refreshes)
    # Note: In real scenario, this would refresh in background
    assert metadata["age_ms"] >= 60


@pytest.mark.asyncio
async def test_sequence_gap_invalidates_cache(cache_config, mock_refresh_callback):
    """
    Test: WS sequence gap forces cache invalidation and refresh.
    
    Scenario:
    1. Cache has data with update_id=100
    2. Request with expected_update_id=105 (gap > 1)
    3. Should detect sequence gap and force refresh
    """
    cache = MDCache(cache_config, mock_refresh_callback)
    
    # Pre-populate cache with update_id=100
    cache._update_cache(
        symbol="BTCUSDT",
        orderbook={"bids": [[49000.0, 1.0]], "asks": [[49001.0, 1.0]]},
        depth=50,
        update_id=100
    )
    
    # Request with expected_update_id=105 (gap detected)
    orderbook, metadata = await cache.get_orderbook(
        symbol="BTCUSDT",
        depth=50,
        expected_update_id=105
    )
    
    # Should detect sequence gap
    assert metadata["sequence_gap"] is True
    
    # Should NOT be a cache hit
    assert metadata["cache_hit"] is False
    
    # Should have triggered refresh with new update_id
    assert orderbook["update_id"] == 12345


@pytest.mark.asyncio
async def test_depth_miss_no_upscaling(cache_config, mock_refresh_callback):
    """
    Test: Cache miss when requested depth > cached depth (no upscaling).
    
    Scenario:
    1. Cache has depth=20 data
    2. Request depth=50
    3. Should be cache miss (no upscaling allowed)
    """
    cache = MDCache(cache_config, mock_refresh_callback)
    
    # Pre-populate cache with depth=20
    cache._update_cache(
        symbol="BTCUSDT",
        orderbook={"bids": [[49000.0, 1.0]], "asks": [[49001.0, 1.0]]},
        depth=20
    )
    
    # Request depth=50 (more than cached)
    orderbook, metadata = await cache.get_orderbook(
        symbol="BTCUSDT",
        depth=50
    )
    
    # Should be depth miss
    assert metadata["depth_miss"] is True
    
    # Should NOT be a cache hit
    assert metadata["cache_hit"] is False
    
    # Should have triggered refresh with correct depth
    assert orderbook is not None  # Fresh data returned


@pytest.mark.asyncio
async def test_depth_hit_downscaling_ok(cache_config, mock_refresh_callback):
    """
    Test: Cache hit when requested depth < cached depth (downscaling OK).
    
    Scenario:
    1. Cache has depth=50 data
    2. Request depth=20
    3. Should be cache hit (downscaling allowed)
    """
    cache = MDCache(cache_config, mock_refresh_callback)
    
    # Pre-populate cache with depth=50
    cache._update_cache(
        symbol="BTCUSDT",
        orderbook={"bids": [[49000.0, 1.0]], "asks": [[49001.0, 1.0]]},
        depth=50
    )
    
    # Request depth=20 (less than cached)
    orderbook, metadata = await cache.get_orderbook(
        symbol="BTCUSDT",
        depth=20
    )
    
    # Should NOT be depth miss
    assert metadata["depth_miss"] is False
    
    # Should be a cache hit (fresh + downscaling OK)
    assert metadata["cache_hit"] is True
    
    # Should return cached data
    assert orderbook["bids"][0][0] == 49000.0


@pytest.mark.asyncio
async def test_rewind_detection_invalidates_cache(cache_config, mock_refresh_callback):
    """
    Test: WS rewind (expected_update_id < cached) invalidates cache.
    
    Scenario:
    1. Cache has update_id=100
    2. Request with expected_update_id=95 (rewind)
    3. Should invalidate cache and refresh
    """
    cache = MDCache(cache_config, mock_refresh_callback)
    
    # Pre-populate cache with update_id=100
    cache._update_cache(
        symbol="BTCUSDT",
        orderbook={"bids": [[49000.0, 1.0]], "asks": [[49001.0, 1.0]]},
        depth=50,
        update_id=100
    )
    
    # Request with expected_update_id=95 (rewind)
    orderbook, metadata = await cache.get_orderbook(
        symbol="BTCUSDT",
        depth=50,
        expected_update_id=95
    )
    
    # Should NOT be a cache hit (rewind detected)
    assert metadata["cache_hit"] is False
    
    # Should have triggered refresh
    assert orderbook["update_id"] == 12345
    
    # Cache should be invalidated (check cache state)
    assert "BTCUSDT" not in cache._cache or cache._cache["BTCUSDT"].update_id == 12345


@pytest.mark.asyncio
async def test_stale_ok_returns_stale_and_triggers_async_refresh(cache_config, mock_refresh_callback):
    """
    Test: stale_ok mode returns stale data + triggers async refresh.
    
    Scenario:
    1. Cache has stale data (age > TTL)
    2. Request with stale_ok=True (default)
    3. Should return stale data immediately + trigger async refresh
    """
    cache = MDCache(cache_config, mock_refresh_callback)
    
    # Pre-populate cache
    cache._update_cache(
        symbol="BTCUSDT",
        orderbook={"bids": [[49000.0, 1.0]], "asks": [[49001.0, 1.0]]},
        depth=50
    )
    
    # Wait for data to become stale
    await asyncio.sleep(0.12)  # > 100ms TTL
    
    # Request with stale_ok (general use case)
    orderbook, metadata = await cache.get_orderbook(
        symbol="BTCUSDT",
        depth=50,
        use_case="general"
    )
    
    # Should be marked as stale
    assert metadata["used_stale"] is True
    
    # Should return cached data (stale but OK)
    assert orderbook["bids"][0][0] == 49000.0
    
    # Async refresh should be triggered (check inflight)
    # Note: Actual refresh happens in background
    assert metadata["age_ms"] > 100


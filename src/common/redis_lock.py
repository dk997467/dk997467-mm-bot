"""
Distributed lock using Redis for idempotency.

Features:
- Async context manager
- Auto-extend lock TTL
- Graceful fallback if Redis unavailable
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional
from contextlib import asynccontextmanager


class RedisLock:
    """
    Distributed lock using Redis SETNX with TTL.
    
    Features:
    - Auto-extend lock while held
    - Unique lock value (prevents unlock by wrong holder)
    - Graceful fallback if Redis unavailable
    
    Usage:
        async with RedisLock(redis, "freeze:session_123", ttl=30) as acquired:
            if acquired:
                # Only one process executes this
                await cancel_all_orders()
            else:
                # Already locked by another process
                logger.info("Lock already held")
    """
    
    def __init__(
        self,
        redis_client: Optional[Any],
        key: str,
        ttl: int = 30,
        extend_every: int = 10
    ):
        """
        Initialize Redis lock.
        
        Args:
            redis_client: Redis async client (or None for no-op)
            key: Lock key name
            ttl: Lock TTL in seconds
            extend_every: Extend lock every N seconds
        """
        self.redis = redis_client
        self.key = key
        self.ttl = ttl
        self.extend_every = extend_every
        self.lock_value = str(uuid.uuid4())
        self._extend_task: Optional[asyncio.Task] = None
        self._acquired = False
    
    async def acquire(self) -> bool:
        """
        Acquire lock.
        
        Returns:
            True if lock acquired, False if already held
        """
        if self.redis is None:
            # No Redis: always acquire (single-process mode)
            self._acquired = True
            return True
        
        try:
            # SETNX with TTL
            result = await self.redis.set(
                self.key,
                self.lock_value,
                ex=self.ttl,
                nx=True  # Only set if not exists
            )
            
            self._acquired = bool(result)
            
            if self._acquired:
                # Start auto-extend task
                self._extend_task = asyncio.create_task(self._auto_extend())
            
            return self._acquired
        
        except Exception:
            # Redis error: fall back to acquiring (fail-open)
            self._acquired = True
            return True
    
    async def release(self) -> None:
        """Release lock."""
        if self._extend_task:
            self._extend_task.cancel()
            try:
                await self._extend_task
            except asyncio.CancelledError:
                pass
        
        if not self._acquired or self.redis is None:
            return
        
        try:
            # Lua script: only delete if value matches (prevent wrong holder from unlocking)
            script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            await self.redis.eval(script, 1, self.key, self.lock_value)
        
        except Exception:
            pass  # Best-effort release
        
        self._acquired = False
    
    async def _auto_extend(self) -> None:
        """Background task to auto-extend lock TTL."""
        try:
            while True:
                await asyncio.sleep(self.extend_every)
                
                if self.redis is None:
                    break
                
                try:
                    # Lua script: extend TTL only if value matches
                    script = """
                    if redis.call("get", KEYS[1]) == ARGV[1] then
                        return redis.call("expire", KEYS[1], ARGV[2])
                    else
                        return 0
                    end
                    """
                    await self.redis.eval(script, 1, self.key, self.lock_value, self.ttl)
                
                except Exception:
                    # Extend failed: stop extending (lock may have expired)
                    break
        
        except asyncio.CancelledError:
            pass
    
    async def __aenter__(self):
        """Context manager entry."""
        acquired = await self.acquire()
        return acquired
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.release()
        return False


@asynccontextmanager
async def distributed_lock(
    redis_client: Optional[Any],
    key: str,
    ttl: int = 30,
    extend_every: int = 10
):
    """
    Async context manager for distributed lock.
    
    Usage:
        async with distributed_lock(redis, "my_lock") as acquired:
            if acquired:
                # Critical section
                pass
    """
    lock = RedisLock(redis_client, key, ttl, extend_every)
    acquired = await lock.acquire()
    try:
        yield acquired
    finally:
        await lock.release()


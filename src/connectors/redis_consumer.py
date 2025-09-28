"""
Async Redis consumer for normalized market data events.

Usage:
    consumer = RedisMDConsumer(redis_url, key="md:ticks", kind="stream")
    async for ev in consumer.iter_events():
        ...
"""

import asyncio
import os
from typing import AsyncIterator, Dict, Optional, Tuple

import redis.asyncio as aioredis
import orjson


class RedisMDConsumer:
    """Redis-based async consumer for market data events.

    Supports Redis Streams (XREAD) and Lists (BLPOP) via 'kind' parameter.
    Each event expects a field 'data' containing a JSON-encoded payload or the list item value encoding JSON directly.
    """

    def __init__(self, redis_url: str, key: str = "md:ticks", kind: str = "stream", group: Optional[str] = None, consumer: Optional[str] = None):
        self.redis_url = redis_url
        self.key = key
        self.kind = kind.lower()
        self.group = group
        self.consumer = consumer or f"c-{os.getpid()}"
        self._client: Optional[aioredis.Redis] = None
        self._stop = asyncio.Event()

    async def start(self):
        self._client = aioredis.from_url(self.redis_url)
        # For streams consumer group, ensure group exists
        if self.kind == "stream" and self.group:
            try:
                await self._client.xgroup_create(name=self.key, groupname=self.group, id="0-0", mkstream=True)
            except Exception:
                # Likely BUSYGROUP, ignore
                pass

    async def stop(self):
        self._stop.set()
        if self._client:
            await self._client.close()
            self._client = None

    async def iter_events(self, block_ms: int = 1000) -> AsyncIterator[Dict]:
        """Yield events as dict parsed via orjson.

        - For Streams without group: XREAD block
        - For Streams with group: XREADGROUP block
        - For Lists: BLPOP
        """
        if self._client is None:
            await self.start()
        assert self._client is not None

        if self.kind == "list":
            async for ev in self._iter_list(block_ms):
                yield ev
        else:
            async for ev in self._iter_stream(block_ms):
                yield ev

    async def _iter_list(self, block_ms: int) -> AsyncIterator[Dict]:
        assert self._client is not None
        while not self._stop.is_set():
            try:
                # BLPOP returns (key, value)
                res = await self._client.blpop(self.key, timeout=block_ms / 1000.0)
                if not res:
                    continue
                _key, value = res
                if isinstance(value, (bytes, bytearray)):
                    ev = orjson.loads(value)
                else:
                    ev = orjson.loads(str(value).encode("utf-8"))
                yield ev
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)
                continue

    async def _iter_stream(self, block_ms: int) -> AsyncIterator[Dict]:
        assert self._client is not None
        last_id = "$" if not self.group else ">"
        while not self._stop.is_set():
            try:
                if self.group:
                    # XREADGROUP GROUP group consumer BLOCK ... COUNT 100 STREAMS key >
                    msgs = await self._client.xreadgroup(self.group, self.consumer, streams={self.key: last_id}, count=100, block=block_ms)
                else:
                    msgs = await self._client.xread({self.key: last_id}, count=100, block=block_ms)
                if not msgs:
                    continue
                for stream, entries in msgs:
                    for msg_id, fields in entries:
                        data = fields.get("data")
                        if isinstance(data, (bytes, bytearray)):
                            ev = orjson.loads(data)
                        elif data is None and fields:
                            # Sometimes payload stored as fields
                            ev = {k.decode() if isinstance(k, (bytes, bytearray)) else k: v for k, v in fields.items()}
                        else:
                            ev = orjson.loads(str(data).encode("utf-8"))
                        yield ev
                        if self.group:
                            # Acknowledge message
                            await self._client.xack(self.key, self.group, msg_id)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.1)
                continue

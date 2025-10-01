"""
Bybit WebSocket connector with hardened connectivity and reconnection logic.
"""

import asyncio
import json
import time
import random
from typing import Any, Callable, Dict, Optional, List
from dataclasses import dataclass

import aiohttp
import orjson

from src.common.di import AppContext
from src.metrics.exporter import Metrics


@dataclass
class WebSocketMessage:
    """WebSocket message wrapper."""
    topic: str
    data: Dict[str, Any]
    timestamp: float


class BybitWebSocketConnector:
    """Hardened Bybit WebSocket connector with reconnection logic and metrics."""
    
    def __init__(self, ctx: AppContext, config: Dict[str, Any], 
                 on_orderbook_update: Optional[Callable] = None,
                 on_trade_update: Optional[Callable] = None,
                 on_order_update: Optional[Callable] = None,
                 on_execution_update: Optional[Callable] = None,
                 on_orderbook_delta: Optional[Callable] = None):
        """Initialize connector with AppContext and config."""
        self.ctx = ctx
        self.config = config
        self.on_orderbook_update = on_orderbook_update
        self.on_trade_update = on_trade_update
        self.on_order_update = on_order_update
        self.on_execution_update = on_execution_update
        self.on_orderbook_delta = on_orderbook_delta
        
        # Connection state
        self.connected = False
        self._ws_public: Optional[aiohttp.ClientWebSocketResponse] = None
        self._ws_private: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        
        # WebSocket URLs
        self.public_ws_url = config.get('public_ws_url', 'wss://stream.bybit.com/v5/public/linear')
        self.private_ws_url = config.get('private_ws_url', 'wss://stream.bybit.com/v5/private')
        
        # Reconnection configuration
        self.max_reconnect_attempts = config.get('max_reconnect_attempts', 10)
        self.base_reconnect_delay = config.get('base_reconnect_delay', 1.0)
        self.max_reconnect_delay = config.get('max_reconnect_delay', 60.0)
        self.heartbeat_interval = config.get('heartbeat_interval', 30)
        
        # Metrics
        self.metrics: Optional[Metrics] = None
        if hasattr(ctx, 'metrics'):
            self.metrics = ctx.metrics
        
        # Reconnection state
        self._reconnect_attempts = 0
        self._last_heartbeat = 0
        self._stop_requested = False
        # Heartbeat task handles
        self._hb_pub_task: Optional[asyncio.Task] = None
        self._hb_prv_task: Optional[asyncio.Task] = None
        
        # Subscriptions
        self._public_subscriptions: List[str] = []
        self._private_subscriptions: List[str] = []
    
    async def start(self):
        """Start WebSocket connections with reconnection logic."""
        self._stop_requested = False
        self._session = aiohttp.ClientSession()
        
        # Start both connections
        await asyncio.gather(self._connect_public_websocket(), self._connect_private_websocket())
        
        self.connected = True
    
    async def stop(self):
        """Stop WebSocket connections."""
        self._stop_requested = True
        self.connected = False
        
        # cancel heartbeats first
        try:
            if self._hb_pub_task:
                self._hb_pub_task.cancel()
            if self._hb_prv_task:
                self._hb_prv_task.cancel()
            await asyncio.gather(*[t for t in (self._hb_pub_task, self._hb_prv_task) if t], return_exceptions=True)
        except Exception:
            pass
        # close sockets & session
        try:
            if self._ws_public:
                await self._ws_public.close()
        except Exception:
            pass
        try:
            if self._ws_private:
                await self._ws_private.close()
        except Exception:
            pass
        try:
            if self._session:
                await self._session.close()
        except Exception:
            pass
        self._ws_public = None
        self._ws_private = None
        self._session = None
    
    def is_connected(self) -> bool:
        """Check if connector is connected."""
        return (self.connected and 
                self._ws_public is not None and 
                self._ws_private is not None)
    
    def get_connection_status(self) -> Dict[str, bool]:
        """Get connection status."""
        return {
            "public": self._ws_public is not None and not self._ws_public.closed,
            "private": self._ws_private is not None and not self._ws_private.closed
        }
    
    async def _connect_public_websocket(self):
        """Connect to public WebSocket with reconnection logic."""
        while not self._stop_requested:
            try:
                if self._session is None:
                    break
                
                async with self._session.ws_connect(self.public_ws_url) as ws:
                    self._ws_public = ws
                    
                    # CRITICAL: Reset reconnect attempts on successful connection
                    self._reconnect_attempts = 0
                    
                    # Resubscribe to topics
                    for topic in self._public_subscriptions:
                        await self._subscribe_public(topic)
                    
                    # Start heartbeat
                    self._hb_pub_task = asyncio.create_task(self._heartbeat_public())
                    
                    # Process messages
                    async for msg in ws:
                        if self._stop_requested:
                            break
                        
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_public_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            print(f"Public WebSocket error: {ws.exception()}")
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSE:
                            break
                
            except Exception as e:
                print(f"Public WebSocket connection error: {e}")
                if self.metrics:
                    self.metrics.ws_reconnects_total.labels(exchange="bybit").inc()
            
            # Reconnection logic
            if not self._stop_requested:
                should_stop = await self._wait_before_reconnect("public")
                if should_stop:
                    print("[CRITICAL] Public WebSocket: max reconnect attempts reached, stopping...")
                    self._stop_requested = True
                    break
    
    async def _connect_private_websocket(self):
        """Connect to private WebSocket with reconnection logic."""
        while not self._stop_requested:
            try:
                if self._session is None:
                    break
                
                # Private WebSocket requires authentication
                headers = self._get_auth_headers()
                
                async with self._session.ws_connect(self.private_ws_url, headers=headers) as ws:
                    self._ws_private = ws
                    
                    # CRITICAL: Reset reconnect attempts on successful connection
                    self._reconnect_attempts = 0
                    
                    # Resubscribe to topics
                    for topic in self._private_subscriptions:
                        await self._subscribe_private(topic)
                    
                    # Start heartbeat
                    self._hb_prv_task = asyncio.create_task(self._heartbeat_private())
                    
                    # Process messages
                    async for msg in ws:
                        if self._stop_requested:
                            break
                        
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_private_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            print(f"Private WebSocket error: {ws.exception()}")
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSE:
                            break
                
            except Exception as e:
                print(f"Private WebSocket connection error: {e}")
                if self.metrics:
                    self.metrics.ws_reconnects_total.labels(exchange="bybit").inc()
            
            # Reconnection logic
            if not self._stop_requested:
                should_stop = await self._wait_before_reconnect("private")
                if should_stop:
                    print("[CRITICAL] Private WebSocket: max reconnect attempts reached, stopping...")
                    self._stop_requested = True
                    break
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for private WebSocket."""
        # This is a simplified version - in production you'd need proper signature generation
        return {
            "api_key": self.config.get("api_key", ""),
            "timestamp": str(int(time.time() * 1000)),
            "recv_window": str(self.config.get("recv_window", 5000))
        }
    
    async def _wait_before_reconnect(self, ws_type: str = "unknown") -> bool:
        """
        Wait before attempting reconnection with exponential backoff and jitter.
        
        Implements industry-standard exponential backoff:
        - Base delay doubles with each attempt (exponential growth)
        - Jitter adds randomness to prevent synchronized reconnects (thundering herd)
        - Max delay cap prevents excessive wait times
        - Max attempts prevents infinite retry loops
        
        Formula: delay = min(base * 2^attempt + jitter, max_delay)
        where jitter = random(0, delay * 0.3) to add 30% variance
        
        Args:
            ws_type: WebSocket type for logging ("public" or "private")
        
        Returns:
            True if max attempts reached (caller should stop), False otherwise
        
        Example backoff sequence (base=1s, max=60s):
        - Attempt 1: ~1s  (1 * 2^0 + jitter)
        - Attempt 2: ~2s  (1 * 2^1 + jitter)
        - Attempt 3: ~4s  (1 * 2^2 + jitter)
        - Attempt 4: ~8s  (1 * 2^3 + jitter)
        - Attempt 5: ~16s (1 * 2^4 + jitter)
        - Attempt 6: ~32s (1 * 2^5 + jitter)
        - Attempt 7+: ~60s (capped at max_delay)
        """
        # Check if max attempts reached
        if self._reconnect_attempts >= self.max_reconnect_attempts:
            print(f"[CRITICAL] {ws_type.upper()} WebSocket: max reconnect attempts ({self.max_reconnect_attempts}) reached")
            if self.metrics:
                self.metrics.ws_max_reconnect_reached_total.labels(
                    exchange="bybit",
                    ws_type=ws_type
                ).inc()
            return True  # Signal caller to stop
        
        # Calculate exponential backoff
        exponential_delay = self.base_reconnect_delay * (2 ** self._reconnect_attempts)
        
        # Add jitter (30% of delay) to prevent thundering herd
        # This spreads out reconnects from multiple instances
        jitter_range = exponential_delay * 0.3
        jitter = random.uniform(0, jitter_range)
        
        # Apply max cap
        delay = min(exponential_delay + jitter, self.max_reconnect_delay)
        
        self._reconnect_attempts += 1
        
        # Log with full context
        print(
            f"[BACKOFF] {ws_type.upper()} WebSocket reconnect: "
            f"attempt={self._reconnect_attempts}/{self.max_reconnect_attempts}, "
            f"delay={delay:.2f}s (exp={exponential_delay:.2f}s, jitter={jitter:.2f}s)"
        )
        
        # Record metrics
        if self.metrics:
            self.metrics.ws_reconnect_delay_seconds.observe(
                {"exchange": "bybit", "ws_type": ws_type},
                delay
            )
            self.metrics.ws_reconnect_attempts_total.labels(
                exchange="bybit",
                ws_type=ws_type
            ).inc()
        
        # Wait before reconnecting
        await asyncio.sleep(delay)
        
        return False  # Continue retrying
    
    async def _heartbeat_public(self):
        """Send heartbeat to public WebSocket."""
        while not self._stop_requested and self._ws_public and not self._ws_public.closed:
            try:
                await self._ws_public.send_str('{"op": "ping"}')
                self._last_heartbeat = time.time()
                await asyncio.sleep(self.heartbeat_interval)
            except Exception as e:
                print(f"Public heartbeat error: {e}")
                break
    
    async def _heartbeat_private(self):
        """Send heartbeat to private WebSocket."""
        while not self._stop_requested and self._ws_private and not self._ws_private.closed:
            try:
                await self._ws_private.send_str('{"op": "ping"}')
                self._last_heartbeat = time.time()
                await asyncio.sleep(self.heartbeat_interval)
            except Exception as e:
                print(f"Private heartbeat error: {e}")
                break
    
    async def _handle_public_message(self, message_data: str):
        """Handle public WebSocket message."""
        try:
            data = orjson.loads(message_data)
            
            # Record latency
            if self.metrics:
                latency_ms = int((time.time() - data.get('ts', time.time() * 1000) / 1000) * 1000)
                self.metrics.latency_ms.observe({"stage": "ws"}, latency_ms)
            
            # Route message to appropriate handler
            topic = data.get('topic', '')
            
            if 'orderbook' in topic:
                if self.on_orderbook_update:
                    await self.on_orderbook_update(data)
            elif 'trade' in topic:
                if self.on_trade_update:
                    await self.on_trade_update(data)
            elif 'orderbook.delta' in topic:
                if self.on_orderbook_delta:
                    await self.on_orderbook_delta(data)
                    
        except Exception as e:
            print(f"Error handling public message: {e}")
    
    async def _handle_private_message(self, message_data: str):
        """Handle private WebSocket message."""
        try:
            data = orjson.loads(message_data)
            
            # Record latency
            if self.metrics:
                latency_ms = int((time.time() - data.get('ts', time.time() * 1000) / 1000) * 1000)
                self.metrics.latency_ms.observe({"stage": "ws"}, latency_ms)
            
            # Route message to appropriate handler
            topic = data.get('topic', '')
            
            if 'order' in topic:
                if self.on_order_update:
                    await self.on_order_update(data)
            elif 'execution' in topic:
                if self.on_execution_update:
                    await self.on_execution_update(data)
                    
        except Exception as e:
            print(f"Error handling private message: {e}")
    
    async def subscribe_orderbook(self, symbol: str):
        """Subscribe to orderbook updates."""
        topic = f"orderbook.1.{symbol}"
        self._public_subscriptions.append(topic)
        
        if self._ws_public and not self._ws_public.closed:
            await self._subscribe_public(topic)
    
    async def subscribe_trades(self, symbol: str):
        """Subscribe to trade updates."""
        topic = f"publicTrade.{symbol}"
        self._public_subscriptions.append(topic)
        
        if self._ws_public and not self._ws_public.closed:
            await self._subscribe_public(topic)
    
    async def subscribe_orders(self, symbol: str):
        """Subscribe to order updates."""
        topic = f"order.{symbol}"
        self._private_subscriptions.append(topic)
        
        if self._ws_private and not self._ws_private.closed:
            await self._subscribe_private(topic)
    
    async def subscribe_executions(self, symbol: str):
        """Subscribe to execution updates."""
        topic = f"execution.{symbol}"
        self._private_subscriptions.append(topic)
        
        if self._ws_private and not self._ws_private.closed:
            await self._subscribe_private(topic)
    
    async def _subscribe_public(self, topic: str):
        """Subscribe to public topic."""
        if self._ws_public and not self._ws_public.closed:
            subscribe_msg = {
                "op": "subscribe",
                "args": [topic]
            }
            await self._ws_public.send_str(orjson.dumps(subscribe_msg).decode())
    
    async def _subscribe_private(self, topic: str):
        """Subscribe to private topic."""
        if self._ws_private and not self._ws_private.closed:
            subscribe_msg = {
                "op": "subscribe",
                "args": [topic]
            }
            await self._ws_private.send_str(orjson.dumps(subscribe_msg).decode())

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
        
        # Subscriptions
        self._public_subscriptions: List[str] = []
        self._private_subscriptions: List[str] = []
    
    async def start(self):
        """Start WebSocket connections with reconnection logic."""
        self._stop_requested = False
        self._session = aiohttp.ClientSession()
        
        # Start both connections
        await asyncio.gather(
            self._connect_public_websocket(),
            self._connect_private_websocket()
        )
        
        self.connected = True
    
    async def stop(self):
        """Stop WebSocket connections."""
        self._stop_requested = True
        self.connected = False
        
        if self._ws_public:
            await self._ws_public.close()
        if self._ws_private:
            await self._ws_private.close()
        if self._session:
            await self._session.close()
    
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
                    
                    # Resubscribe to topics
                    for topic in self._public_subscriptions:
                        await self._subscribe_public(topic)
                    
                    # Start heartbeat
                    asyncio.create_task(self._heartbeat_public())
                    
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
                await self._wait_before_reconnect()
    
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
                    
                    # Resubscribe to topics
                    for topic in self._private_subscriptions:
                        await self._subscribe_private(topic)
                    
                    # Start heartbeat
                    asyncio.create_task(self._heartbeat_private())
                    
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
                await self._wait_before_reconnect()
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for private WebSocket."""
        # This is a simplified version - in production you'd need proper signature generation
        return {
            "api_key": self.config.get("api_key", ""),
            "timestamp": str(int(time.time() * 1000)),
            "recv_window": str(self.config.get("recv_window", 5000))
        }
    
    async def _wait_before_reconnect(self):
        """Wait before attempting reconnection with exponential backoff."""
        if self._reconnect_attempts >= self.max_reconnect_attempts:
            print("Max reconnection attempts reached")
            return
        
        delay = min(
            self.base_reconnect_delay * (2 ** self._reconnect_attempts) + random.uniform(0, 1),
            self.max_reconnect_delay
        )
        
        self._reconnect_attempts += 1
        print(f"Reconnecting in {delay:.2f} seconds (attempt {self._reconnect_attempts})")
        await asyncio.sleep(delay)
    
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

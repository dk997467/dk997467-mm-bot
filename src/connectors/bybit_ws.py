"""
Bybit V5 WebSocket connector.
"""

import asyncio
import hashlib
import hmac
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

try:
    from common.config import Config
    from common.models import MarketDataEvent, OrderBook, PriceLevel, Side
    from common.utils import timestamp_to_datetime, parse_decimal, json_loads, json_dumps
except ImportError:
    from src.common.config import Config
    from src.common.models import MarketDataEvent, OrderBook, PriceLevel, Side
    from src.common.utils import timestamp_to_datetime, parse_decimal, json_loads, json_dumps


class BybitWebSocketConnector:
    """Bybit V5 WebSocket connector with authentication and auto-reconnect."""
    
    def __init__(
        self, 
        config: Config,
        on_orderbook_update: Optional[Callable[[OrderBook], None]] = None,
        on_trade_update: Optional[Callable[[Dict], None]] = None,
        on_order_update: Optional[Callable[[Dict], None]] = None,
        on_execution_update: Optional[Callable[[Dict], None]] = None,
        on_orderbook_delta: Optional[Callable[[str, Dict], None]] = None
    ):
        """Initialize the WebSocket connector."""
        self.config = config
        self.callbacks = {
            'orderbook': on_orderbook_update,
            'trade': on_trade_update,
            'order': on_order_update,
            'execution': on_execution_update,
            'orderbook_delta': on_orderbook_delta,
        }
        
        # WebSocket connections
        self.public_ws: Optional[websockets.WebSocketServerProtocol] = None
        self.private_ws: Optional[websockets.WebSocketServerProtocol] = None
        
        # Connection state
        self.public_connected = False
        self.private_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = config.websocket.max_reconnect_attempts
        
        # Sequence tracking
        self.public_sequence: Dict[str, int] = {}
        self.private_sequence: Dict[str, int] = {}
        
        # Subscriptions
        self.public_subscriptions: Set[str] = set()
        self.private_subscriptions: Set[str] = set()
        
        # Ping/pong tracking
        self.last_ping_time = 0
        self.last_pong_time = 0
        self.ping_interval = config.websocket.ping_interval_sec
        self.pong_timeout = config.websocket.pong_timeout_sec
        
        # Running state
        self.running = False
        self.tasks: List[asyncio.Task] = []
    
    async def start(self):
        """Start the WebSocket connections."""
        self.running = True
        
        # Start public WebSocket
        self.tasks.append(asyncio.create_task(self._run_public_websocket()))
        
        # Start private WebSocket
        self.tasks.append(asyncio.create_task(self._run_private_websocket()))
        
        # Start ping/pong monitoring
        self.tasks.append(asyncio.create_task(self._ping_pong_monitor()))
        
        # Wait for connections to establish
        await asyncio.sleep(2)
        
        # Subscribe to market data
        await self._subscribe_public_channels()
        await self._subscribe_private_channels()
    
    async def stop(self):
        """Stop the WebSocket connections."""
        self.running = False
        
        # Cancel all tasks
        for task in self.tasks:
            task.cancel()
        
        # Close connections
        if self.public_ws:
            await self.public_ws.close()
        if self.private_ws:
            await self.private_ws.close()
        
        # Wait for tasks to complete
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
    
    async def _run_public_websocket(self):
        """Run the public WebSocket connection."""
        while self.running:
            try:
                await self._connect_public_websocket()
                await self._handle_public_messages()
            except Exception as e:
                print(f"Public WebSocket error: {e}")
                await self._handle_public_disconnect()
            
            if self.running:
                await asyncio.sleep(self.config.websocket.reconnect_delay_ms / 1000)
    
    async def _run_private_websocket(self):
        """Run the private WebSocket connection."""
        while self.running:
            try:
                await self._connect_private_websocket()
                await self._handle_private_messages()
            except Exception as e:
                print(f"Private WebSocket error: {e}")
                await self._handle_private_disconnect()
            
            if self.running:
                await asyncio.sleep(self.config.websocket.reconnect_delay_ms / 1000)
    
    async def _connect_public_websocket(self):
        """Connect to public WebSocket."""
        try:
            self.public_ws = await websockets.connect(
                self.config.bybit.ws_public_url,
                ping_interval=None,  # We handle ping/pong manually
                ping_timeout=None
            )
            self.public_connected = True
            self.reconnect_attempts = 0
            print("Public WebSocket connected")
        except Exception as e:
            print(f"Failed to connect to public WebSocket: {e}")
            raise
    
    async def _connect_private_websocket(self):
        """Connect to private WebSocket with authentication."""
        try:
            # Generate authentication parameters
            timestamp = int(time.time() * 1000)
            recv_window = 5000
            
            params = {
                "api_key": self.config.bybit.api_key,
                "timestamp": timestamp,
                "recv_window": recv_window
            }
            
            # Generate signature
            query_string = urlencode(params)
            signature = hmac.new(
                self.config.bybit.api_secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Add signature to parameters
            params["sign"] = signature
            
            # Connect to WebSocket
            ws_url = f"{self.config.bybit.ws_private_url}?{urlencode(params)}"
            self.private_ws = await websockets.connect(
                ws_url,
                ping_interval=None,
                ping_timeout=None
            )
            
            self.private_connected = True
            self.reconnect_attempts = 0
            print("Private WebSocket connected")
            
        except Exception as e:
            print(f"Failed to connect to private WebSocket: {e}")
            raise
    
    async def _handle_public_messages(self):
        """Handle incoming public WebSocket messages."""
        if not self.public_ws:
            return
        
        try:
            async for message in self.public_ws:
                if not self.running:
                    break
                
                try:
                    data = json_loads(message)
                    await self._process_public_message(data)
                except Exception as e:
                    print(f"Error processing public message: {e}")
                    
        except ConnectionClosed:
            print("Public WebSocket connection closed")
            raise
        except Exception as e:
            print(f"Public WebSocket error: {e}")
            raise
    
    async def _handle_private_messages(self):
        """Handle incoming private WebSocket messages."""
        if not self.private_ws:
            return
        
        try:
            async for message in self.private_ws:
                if not self.running:
                    break
                
                try:
                    data = json_loads(message)
                    await self._process_private_message(data)
                except Exception as e:
                    print(f"Error processing private message: {e}")
                    
        except ConnectionClosed:
            print("Private WebSocket connection closed")
            raise
        except Exception as e:
            print(f"Private WebSocket error: {e}")
            raise
    
    async def _process_public_message(self, data: Dict[str, Any]):
        """Process public WebSocket message."""
        topic = data.get("topic", "")
        
        if "orderbook" in topic:
            await self._handle_orderbook_update(data)
        elif "tickers" in topic:
            await self._handle_ticker_update(data)
        elif "publicTrade" in topic:
            await self._handle_trade_update(data)
        elif "pong" in data:
            self.last_pong_time = time.time()
        else:
            print(f"Unknown public topic: {topic}")
    
    async def _process_private_message(self, data: Dict[str, Any]):
        """Process private WebSocket message."""
        topic = data.get("topic", "")
        
        if "order" in topic:
            await self._handle_order_update(data)
        elif "execution" in topic:
            await self._handle_execution_update(data)
        elif "position" in topic:
            await self._handle_position_update(data)
        elif "wallet" in topic:
            await self._handle_wallet_update(data)
        elif "pong" in data:
            self.last_pong_time = time.time()
        else:
            print(f"Unknown private topic: {topic}")
    
    async def _handle_orderbook_update(self, data: Dict[str, Any]):
        """Handle orderbook update message."""
        try:
            result = data.get("data", {})
            symbol = result.get("s", "")
            timestamp = timestamp_to_datetime(int(result.get("ts", 0)))
            
            # Parse orderbook data
            bids = []
            asks = []
            
            # Handle snapshot vs delta
            if "b" in result and "a" in result and data.get("type") == "snapshot":
                for bid in result["b"]:
                    bids.append(PriceLevel(
                        price=parse_decimal(bid[0]),
                        size=parse_decimal(bid[1])
                    ))
                for ask in result["a"]:
                    asks.append(PriceLevel(
                        price=parse_decimal(ask[0]),
                        size=parse_decimal(ask[1])
                    ))
                
                # Create orderbook object
                orderbook = OrderBook(
                    symbol=symbol,
                    timestamp=timestamp,
                    sequence=result.get("u", 0),
                    bids=bids,
                    asks=asks
                )
                
                # Sequence tracking and resync detection
                if symbol in self.public_sequence:
                    expected_seq = self.public_sequence[symbol] + 1
                    if result.get("u", 0) != expected_seq:
                        print(f"Sequence gap detected for {symbol}: expected {expected_seq}, got {result.get('u', 0)}")
                        await self._resync_orderbook(symbol)
                self.public_sequence[symbol] = result.get("u", 0)
                
                # Call snapshot callback
                if self.callbacks['orderbook']:
                    self.callbacks['orderbook'](orderbook)
            else:
                # Delta update
                delta_data: Dict[str, Any] = {
                    "u": result.get("u", 0)
                }
                if "b" in result:
                    delta_data["b"] = result["b"]
                if "a" in result:
                    delta_data["a"] = result["a"]
                
                # Sequence tracking and resync detection
                if symbol in self.public_sequence:
                    expected_seq = self.public_sequence[symbol] + 1
                    if result.get("u", 0) != expected_seq:
                        print(f"Sequence gap detected for {symbol}: expected {expected_seq}, got {result.get('u', 0)}")
                        await self._resync_orderbook(symbol)
                self.public_sequence[symbol] = result.get("u", 0)
                
                # Emit delta callback
                if self.callbacks.get('orderbook_delta'):
                    self.callbacks['orderbook_delta'](symbol, delta_data)
        
        except Exception as e:
            print(f"Error handling orderbook update: {e}")
    
    async def _handle_ticker_update(self, data: Dict[str, Any]):
        """Handle ticker update message."""
        # Implement ticker handling if needed
        pass
    
    async def _handle_trade_update(self, data: Dict[str, Any]):
        """Handle public trade update message."""
        if self.callbacks['trade']:
            self.callbacks['trade'](data)
    
    async def _handle_order_update(self, data: Dict[str, Any]):
        """Handle order update message."""
        if self.callbacks['order']:
            self.callbacks['order'](data)
    
    async def _handle_execution_update(self, data: Dict[str, Any]):
        """Handle execution update message."""
        if self.callbacks['execution']:
            self.callbacks['execution'](data)
    
    async def _handle_position_update(self, data: Dict[str, Any]):
        """Handle position update message."""
        # Implement position handling if needed
        pass
    
    async def _handle_wallet_update(self, data: Dict[str, Any]):
        """Handle wallet update message."""
        # Implement wallet handling if needed
        pass
    
    async def _subscribe_public_channels(self):
        """Subscribe to public market data channels."""
        if not self.public_ws or not self.public_connected:
            return
        
        subscriptions = []
        
        # Subscribe to orderbook for all symbols
        for symbol in self.config.trading.symbols:
            subscriptions.append({
                "op": "subscribe",
                "args": [f"orderbook.25.{symbol}"]
            })
            self.public_subscriptions.add(f"orderbook.25.{symbol}")
        
        # Subscribe to tickers
        for symbol in self.config.trading.symbols:
            subscriptions.append({
                "op": "subscribe",
                "args": [f"tickers.{symbol}"]
            })
            self.public_subscriptions.add(f"tickers.{symbol}")
        
        # Send subscriptions
        for sub in subscriptions:
            try:
                await self.public_ws.send(json_dumps(sub))
                print(f"Subscribed to: {sub['args']}")
                await asyncio.sleep(0.1)  # Small delay between subscriptions
            except Exception as e:
                print(f"Failed to subscribe to {sub['args']}: {e}")
    
    async def _subscribe_private_channels(self):
        """Subscribe to private channels."""
        if not self.private_ws or not self.private_connected:
            return
        
        subscriptions = [
            {
                "op": "subscribe",
                "args": ["order"]
            },
            {
                "op": "subscribe",
                "args": ["execution"]
            },
            {
                "op": "subscribe",
                "args": ["position"]
            },
            {
                "op": "subscribe",
                "args": ["wallet"]
            }
        ]
        
        for sub in subscriptions:
            try:
                await self.private_ws.send(json_dumps(sub))
                print(f"Subscribed to private channel: {sub['args']}")
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Failed to subscribe to private channel {sub['args']}: {e}")
    
    async def _resync_orderbook(self, symbol: str):
        """Resync orderbook via REST API when sequence gap detected."""
        print(f"Resyncing orderbook for {symbol}")
        # This would trigger a REST API call to get fresh orderbook
        # Implementation depends on the orderbook manager
    
    async def _ping_pong_monitor(self):
        """Monitor ping/pong health and send periodic pings."""
        while self.running:
            try:
                current_time = time.time()
                
                # Send ping if needed
                if current_time - self.last_ping_time >= self.ping_interval:
                    await self._send_ping()
                    self.last_ping_time = current_time
                
                # Check pong timeout
                if (self.last_pong_time > 0 and 
                    current_time - self.last_pong_time > self.pong_timeout):
                    print("Pong timeout detected, reconnecting...")
                    await self._handle_public_disconnect()
                    await self._handle_private_disconnect()
                
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"Error in ping/pong monitor: {e}")
                await asyncio.sleep(1)
    
    async def _send_ping(self):
        """Send ping to both WebSocket connections."""
        ping_msg = {"op": "ping"}
        
        try:
            if self.public_ws and self.public_connected:
                await self.public_ws.send(json_dumps(ping_msg))
        except Exception as e:
            print(f"Failed to send ping to public WebSocket: {e}")
        
        try:
            if self.private_ws and self.private_connected:
                await self.private_ws.send(json_dumps(ping_msg))
        except Exception as e:
            print(f"Failed to send ping to private WebSocket: {e}")
    
    async def _handle_public_disconnect(self):
        """Handle public WebSocket disconnection."""
        self.public_connected = False
        if self.public_ws:
            try:
                await self.public_ws.close()
            except:
                pass
            self.public_ws = None
        
        self.reconnect_attempts += 1
        if self.reconnect_attempts > self.max_reconnect_attempts:
            print("Max reconnection attempts reached for public WebSocket")
            return
        
        print(f"Public WebSocket disconnected, attempting reconnect {self.reconnect_attempts}/{self.max_reconnect_attempts}")
    
    async def _handle_private_disconnect(self):
        """Handle private WebSocket disconnection."""
        self.private_connected = False
        if self.private_ws:
            try:
                await self.private_ws.close()
            except:
                pass
            self.private_ws = None
        
        self.reconnect_attempts += 1
        if self.reconnect_attempts > self.max_reconnect_attempts:
            print("Max reconnection attempts reached for private WebSocket")
            return
        
        print(f"Private WebSocket disconnected, attempting reconnect {self.reconnect_attempts}/{self.max_reconnect_attempts}")
    
    def is_connected(self) -> bool:
        """Check if both WebSocket connections are healthy."""
        return self.public_connected and self.private_connected
    
    def get_connection_status(self) -> Dict[str, bool]:
        """Get connection status for both WebSockets."""
        return {
            "public": self.public_connected,
            "private": self.private_connected,
            "overall": self.is_connected()
        }

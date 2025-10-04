"""
Common test fixtures for the market maker bot tests.

Provides:
- mk_cfg(): AppConfig with tight limits for fast tests
- mk_ctx(mk_cfg): AppContext with fresh Metrics registry
- FakeOrderBook: Mock orderbook with ahead_volume simulation
- FakeREST/FakeWS: Minimal stub connectors

IMPORTANT: Prometheus registry is auto-cleared before each test by conftest.py
at project root. This prevents memory leaks from metric accumulation.
"""

import asyncio
import pytest
import time
from unittest.mock import Mock, AsyncMock
from typing import Dict, Tuple, Optional, Any

from src.common.config import AppConfig, StrategyConfig, LimitsConfig, TradingConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics


@pytest.fixture
def mk_cfg():
    """Create AppConfig with tight limits for fast tests."""
    return AppConfig(
        strategy=StrategyConfig(
            levels_per_side=2,
            min_time_in_book_ms=200,
            replace_threshold_bps=3,
            amend_price_threshold_bps=1.0,
            amend_size_threshold=0.2,
            k_vola_spread=0.95,
            min_spread_bps=2,
            max_spread_bps=25,
            skew_coeff=0.3,
            imbalance_cutoff=0.65
        ),
        limits=LimitsConfig(
            max_active_per_side=2,
            max_create_per_sec=10,
            max_cancel_per_sec=10
        ),
        trading=TradingConfig(
            symbols=["BTCUSDT"],
            max_active_orders_per_side=10,
            price_band_tolerance_bps=2.0,
            maker_fee_bps=1.0,
            taker_fee_bps=2.0
        )
    )


@pytest.fixture
def mk_ctx(mk_cfg):
    """Create AppContext with fresh Metrics registry."""
    ctx = AppContext(cfg=mk_cfg)
    ctx.metrics = Metrics(ctx)
    return ctx


class FakeOrderBook:
    """Mock orderbook with ahead_volume simulation."""
    
    def __init__(self):
        self._ahead_volumes: Dict[Tuple[str, str, float], float] = {}
        self._consumed_volumes: Dict[Tuple[str, str, float], float] = {}
    
    def ahead_volume(self, symbol: str, side: str, price: float) -> float:
        """Get ahead volume for a price level."""
        key = (symbol, side, price)
        base_volume = self._ahead_volumes.get(key, 0.0)
        consumed = self._consumed_volumes.get(key, 0.0)
        return max(0.0, base_volume - consumed)
    
    def set_ahead_volume(self, symbol: str, side: str, price: float, volume: float):
        """Set base ahead volume for a price level."""
        key = (symbol, side, price)
        self._ahead_volumes[key] = volume
        self._consumed_volumes[key] = 0.0
    
    def consume(self, symbol: str, side: str, qty: float):
        """Simulate trade consumption at best price."""
        # Find best price for the side
        best_price = None
        for (s, side_key, price), volume in self._ahead_volumes.items():
            if s == symbol and side_key == side and volume > 0:
                if best_price is None:
                    best_price = price
                elif side == "Buy" and price > best_price:  # Best bid is highest
                    best_price = price
                elif side == "Sell" and price < best_price:  # Best ask is lowest
                    best_price = price
        
        if best_price is not None:
            key = (symbol, side, best_price)
            consumed = self._consumed_volumes.get(key, 0.0)
            self._consumed_volumes[key] = consumed + qty


class FakeREST:
    """Minimal stub REST connector."""
    
    def __init__(self, latency_ms: float = 1.0):
        self.latency_ms = latency_ms
        self.orders: Dict[str, Dict] = {}
        self.order_counter = 0
    
    async def place_order(self, symbol: str, side: str, order_type: str, 
                         qty: float, price: Optional[float] = None, 
                         time_in_force: str = "GTC") -> Dict[str, Any]:
        """Place order with minimal latency."""
        await asyncio.sleep(self.latency_ms / 1000.0)
        
        self.order_counter += 1
        order_id = f"order_{self.order_counter}"
        client_order_id = f"cid_{self.order_counter}"
        
        order_data = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "orderId": order_id,
                "orderLinkId": client_order_id,
                "symbol": symbol,
                "side": side,
                "orderType": order_type,
                "qty": str(qty),
                "price": str(price) if price else "0",
                "timeInForce": time_in_force,
                "status": "New"
            }
        }
        
        self.orders[client_order_id] = order_data["result"]
        return order_data
    
    async def cancel_order(self, symbol: str, order_id: Optional[str] = None,
                          client_order_id: Optional[str] = None) -> Dict[str, Any]:
        """Cancel order with minimal latency."""
        await asyncio.sleep(self.latency_ms / 1000.0)
        
        if client_order_id and client_order_id in self.orders:
            del self.orders[client_order_id]
        
        return {
            "retCode": 0,
            "retMsg": "OK",
            "result": {"status": "Cancelled"}
        }
    
    async def amend_order(self, symbol: str, order_id: Optional[str] = None,
                         client_order_id: Optional[str] = None, 
                         price: Optional[float] = None,
                         qty: Optional[float] = None) -> Dict[str, Any]:
        """Amend order with minimal latency."""
        await asyncio.sleep(self.latency_ms / 1000.0)
        
        if client_order_id and client_order_id in self.orders:
            order = self.orders[client_order_id]
            if price is not None:
                order["price"] = str(price)
            if qty is not None:
                order["qty"] = str(qty)
        
        return {
            "retCode": 0,
            "retMsg": "OK",
            "result": {"status": "Amended"}
        }
    
    def _round_to_tick(self, price: float, symbol: str) -> float:
        """Round price to tick size."""
        # Simple tick size for testing
        tick_size = 0.1 if "BTC" in symbol else 0.01
        return round(price / tick_size) * tick_size
    
    def _round_to_lot(self, qty: float, symbol: str) -> float:
        """Round quantity to lot size."""
        # Simple lot size for testing
        lot_size = 0.001 if "BTC" in symbol else 0.1
        return round(qty / lot_size) * lot_size


class FakeWS:
    """Minimal stub WebSocket connector."""
    
    def __init__(self):
        self.connected = True
        self.subscriptions = set()
    
    async def subscribe_orderbook(self, symbol: str):
        """Subscribe to orderbook updates."""
        self.subscriptions.add(f"orderbook_{symbol}")
    
    async def subscribe_trades(self, symbol: str):
        """Subscribe to trade updates."""
        self.subscriptions.add(f"trades_{symbol}")
    
    async def close(self):
        """Close connection."""
        self.connected = False
        self.subscriptions.clear()

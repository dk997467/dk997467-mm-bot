"""Tests for OrderManager throttle integration."""

import asyncio
from types import SimpleNamespace
from src.execution.order_manager import OrderManager
from src.guards.throttle import ThrottleGuard
from src.common.config import ThrottleConfig


class _RESTStub:
    """Mock REST connector."""
    
    def __init__(self):
        self.orders_placed = []
        self.orders_amended = []
    
    async def place_order(self, **kwargs):
        self.orders_placed.append(kwargs)
        return {"retCode": 0, "result": {"orderId": "12345", "orderLinkId": f"cid_{len(self.orders_placed)}"}}
    
    async def amend_order(self, **kwargs):
        self.orders_amended.append(kwargs)
        return {"retCode": 0, "result": {}}
    
    async def cancel_order(self, **kwargs):
        return {"retCode": 0, "result": {}}
    
    def _round_to_tick(self, price, symbol):
        return round(price, 2)
    
    def _round_to_lot(self, qty, symbol):
        return round(qty, 4)


def test_place_order_throttle_block():
    """Test that place_order is blocked when throttle limit exceeded."""
    cfg = ThrottleConfig(
        window_sec=5.0,
        max_creates_per_sec=0.2,  # 1 create per 5s window
        per_symbol=True
    )
    throttle = ThrottleGuard(cfg)
    
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            strategy=SimpleNamespace(
                amend_price_threshold_bps=10,
                amend_size_threshold=0.1,
                min_time_in_book_ms=100
            )
        ),
        throttle=throttle,
        guard=None,
        scheduler=None,
        schedulers=None
    )
    
    rest = _RESTStub()
    om = OrderManager(ctx, rest)
    
    async def run_test():
        # First order should succeed
        cid1 = await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        assert cid1
        assert len(rest.orders_placed) == 1
        
        # Second order should be throttled
        try:
            await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
            assert False, "Expected throttle_block exception"
        except Exception as e:
            assert "throttle_block" in str(e)
        
        # Still only one order placed
        assert len(rest.orders_placed) == 1
    
    asyncio.run(run_test())


def test_update_order_throttle_block():
    """Test that update_order is blocked when throttle limit exceeded."""
    cfg = ThrottleConfig(
        window_sec=2.0,
        max_amends_per_sec=0.5,  # 1 amend per 2s window
        per_symbol=False
    )
    throttle = ThrottleGuard(cfg)
    
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            strategy=SimpleNamespace(
                amend_price_threshold_bps=10,
                amend_size_threshold=0.1,
                min_time_in_book_ms=0  # Allow immediate amends for test
            )
        ),
        throttle=throttle,
        guard=None,
        scheduler=None,
        schedulers=None
    )
    
    rest = _RESTStub()
    om = OrderManager(ctx, rest)
    
    async def run_test():
        # Place an order first
        cid = await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        
        # First amend - manually trigger throttle event
        throttle.on_event('amend', 'BTCUSDT', 0.0)  # Fill the window
        
        # Now amend should be throttled
        try:
            await om.update_order(cid, new_price=50200.0)
            assert False, "Expected throttle_block exception"
        except Exception as e:
            assert "throttle_block" in str(e)
    
    asyncio.run(run_test())


def test_throttle_per_symbol_isolation():
    """Test that per-symbol throttling isolates symbols."""
    cfg = ThrottleConfig(
        window_sec=5.0,
        max_creates_per_sec=0.2,  # 1 create per 5s window per symbol
        per_symbol=True
    )
    throttle = ThrottleGuard(cfg)
    
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            strategy=SimpleNamespace(
                amend_price_threshold_bps=10,
                amend_size_threshold=0.1,
                min_time_in_book_ms=100
            )
        ),
        throttle=throttle,
        guard=None,
        scheduler=None,
        schedulers=None
    )
    
    rest = _RESTStub()
    om = OrderManager(ctx, rest)
    
    async def run_test():
        # Place order on BTCUSDT
        cid1 = await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        assert cid1
        
        # BTCUSDT should be throttled
        try:
            await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
            assert False, "Expected throttle_block exception"
        except Exception as e:
            assert "throttle_block" in str(e)
        
        # ETHUSDT should still be allowed
        cid2 = await om.place_order("ETHUSDT", "Buy", "Limit", 0.1, 3000.0)
        assert cid2
        
        assert len(rest.orders_placed) == 2
    
    asyncio.run(run_test())

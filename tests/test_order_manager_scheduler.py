"""
OrderManager scheduler guard: block when closed, allow when open.
"""

import asyncio
from types import SimpleNamespace
import pytest

from src.execution.order_manager import OrderManager


class DummyREST:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def place_order(self, **kw): return {"retCode":0,"result":{"orderId":"1","orderLinkId":"cid1"}}
    def _round_to_lot(self, q, s): return q


class _SchedulerStub:
    def __init__(self, open_flag: bool):
        self._open = open_flag
    def is_open(self):
        return self._open
    def is_trade_allowed(self):
        return self._open


class _SchedulerCooldownStub:
    def __init__(self):
        pass
    def is_open(self):
        return True
    def in_cooldown_open(self):
        return True
    def is_trade_allowed(self):
        return False


def test_scheduler_closed_blocks_place_order():
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            trading=SimpleNamespace(symbols=["BTCUSDT"]),
            strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0),
        ),
        metrics=None,
        portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=2)},
        scheduler=_SchedulerStub(False)
    )
    om = OrderManager(ctx, DummyREST())  # type: ignore

    async def _run():
        with pytest.raises(Exception) as e:
            await om.place_order("BTCUSDT","Buy","Limit",qty=0.001,price=100.0)
        assert "scheduler_closed" in str(e.value)
    asyncio.run(_run())


def test_scheduler_cooldown_blocks_place_order():
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            trading=SimpleNamespace(symbols=["BTCUSDT"]),
            strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0),
        ),
        metrics=None,
        portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=2)},
        scheduler=_SchedulerCooldownStub()
    )
    om = OrderManager(ctx, DummyREST())  # type: ignore

    async def _run():
        try:
            await om.place_order("BTCUSDT","Buy","Limit",qty=0.001,price=100.0)
            assert False, "expected exception"
        except Exception as e:
            assert str(e) == "scheduler_cooldown_block"
    asyncio.run(_run())


def test_scheduler_open_allows_place_order():
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            trading=SimpleNamespace(symbols=["BTCUSDT"]),
            strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0),
        ),
        metrics=None,
        portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=2)},
        scheduler=_SchedulerStub(True)
    )
    om = OrderManager(ctx, DummyREST())  # type: ignore

    async def _run():
        cid = await om.place_order("BTCUSDT","Buy","Limit",qty=0.001,price=100.0)
        assert cid
    asyncio.run(_run())



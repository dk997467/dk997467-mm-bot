import asyncio
from types import SimpleNamespace

import pytest

from src.execution.order_manager import OrderManager


class _SchedStub:
    def __init__(self, open_flag: bool, allow_flag: bool = None):
        self._open = open_flag
        self._allow = allow_flag if allow_flag is not None else open_flag

    def is_open(self):
        return self._open

    def is_trade_allowed(self):
        return self._allow


class _RESTStub:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def place_order(self, **kw):
        return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "cid1"}}
    def _round_to_lot(self, q, s):
        return max(0.0, round(q, 4))


@pytest.mark.asyncio
async def test_per_symbol_scheduler_overrides_global():
    cfg = SimpleNamespace(
        trading=SimpleNamespace(symbols=["BTCUSDT", "ETHUSDT"]),
        strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0)
    )
    ctx = SimpleNamespace(
        cfg=cfg,
        metrics=None,
        portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=2), "ETHUSDT": SimpleNamespace(target_usd=100.0, max_levels=2)},
        scheduler=_SchedStub(open_flag=True, allow_flag=True),
        schedulers={"BTCUSDT": _SchedStub(open_flag=False, allow_flag=False)}
    )
    om = OrderManager(ctx, _RESTStub())  # type: ignore

    with pytest.raises(Exception) as ei:
        await om.place_order("BTCUSDT", "Buy", "Limit", qty=0.001, price=30000.0)
    assert "scheduler_closed" in str(ei.value)

    cid = await om.place_order("ETHUSDT", "Buy", "Limit", qty=0.001, price=3000.0)
    assert cid


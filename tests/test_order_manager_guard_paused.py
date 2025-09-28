import pytest
from types import SimpleNamespace

from src.execution.order_manager import OrderManager


class _RESTStub:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def place_order(self, **kw):
        return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "cid1"}}
    def _round_to_lot(self, q, s):
        return max(0.0, round(q, 4))
    async def cancel_order(self, **kw):
        return {"retCode": 0, "result": {}}


@pytest.mark.asyncio
async def test_order_manager_guard_paused_blocks():
    cfg = SimpleNamespace(
        trading=SimpleNamespace(symbols=["BTCUSDT"]),
        strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0)
    )
    ctx = SimpleNamespace(
        cfg=cfg,
        metrics=None,
        portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=2)},
        guard=SimpleNamespace(paused=True)
    )
    om = OrderManager(ctx, _RESTStub())  # type: ignore
    with pytest.raises(Exception) as ei:
        await om.place_order("BTCUSDT", "Buy", "Limit", qty=0.001, price=30000.0)
    assert "guard_paused" in str(ei.value)


@pytest.mark.asyncio
async def test_order_manager_guard_unpaused_allows():
    cfg = SimpleNamespace(
        trading=SimpleNamespace(symbols=["ETHUSDT"]),
        strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0)
    )
    ctx = SimpleNamespace(
        cfg=cfg,
        metrics=None,
        portfolio_targets={"ETHUSDT": SimpleNamespace(target_usd=100.0, max_levels=2)},
        guard=SimpleNamespace(paused=False)
    )
    om = OrderManager(ctx, _RESTStub())  # type: ignore
    cid = await om.place_order("ETHUSDT", "Buy", "Limit", qty=0.001, price=3000.0)
    assert cid


@pytest.mark.asyncio
async def test_amend_replace_blocked_but_cancel_allowed():
    cfg = SimpleNamespace(
        trading=SimpleNamespace(symbols=["BTCUSDT"]),
        strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0)
    )
    ctx = SimpleNamespace(
        cfg=cfg,
        metrics=None,
        portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=3)},
        guard=SimpleNamespace(paused=False)
    )
    om = OrderManager(ctx, _RESTStub())  # type: ignore
    # place ok
    cid = await om.place_order("BTCUSDT", "Buy", "Limit", qty=0.001, price=30000.0)
    assert cid
    # pause
    ctx.guard.paused = True
    # amend blocked
    with pytest.raises(Exception) as ei:
        await om.update_order(cid, new_price=30010.0)
    assert "guard_paused" in str(ei.value)
    # replace blocked
    with pytest.raises(Exception) as ei2:
        await om._replace_order_cancel_create(cid, new_price=30005.0, new_qty=0.0015, reason="test")
    assert "guard_paused" in str(ei2.value)
    # cancel allowed
    ok = await om.cancel_order(cid)
    assert ok is True


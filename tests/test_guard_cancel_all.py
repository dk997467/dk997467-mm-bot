import pytest
from types import SimpleNamespace

from src.execution.order_manager import OrderManager


class _RESTStub:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def place_order(self, **kw):
        # Use price to generate a unique client order id for testing
        cid = str(kw.get('price', 'cidX'))
        return {"retCode": 0, "result": {"orderId": cid, "orderLinkId": cid}}
    def _round_to_lot(self, q, s):
        return max(0.0, round(q, 4))
    async def cancel_order(self, **kw):
        return {"retCode": 0, "result": {}}


@pytest.mark.asyncio
async def test_guard_cancel_all_for_symbol():
    cfg = SimpleNamespace(
        trading=SimpleNamespace(symbols=["BTCUSDT"]),
        strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0)
    )
    metrics = SimpleNamespace(
        guard_cancels_total=SimpleNamespace(inc=lambda *a, **k: None),
        portfolio_active_usd=SimpleNamespace(labels=lambda **kw: SimpleNamespace(set=lambda v: None)),
        portfolio_active_levels=SimpleNamespace(labels=lambda **kw: SimpleNamespace(set=lambda v: None)),
        creates_total=SimpleNamespace(labels=lambda **kw: SimpleNamespace(inc=lambda *a, **k: None)),
        orders_active=SimpleNamespace(labels=lambda **kw: SimpleNamespace(inc=lambda *a, **k: None, dec=lambda *a, **k: None)),
        cancels_total=SimpleNamespace(labels=lambda **kw: SimpleNamespace(inc=lambda *a, **k: None)),
    )
    ctx = SimpleNamespace(
        cfg=cfg,
        metrics=metrics,
        portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=3)},
        guard=SimpleNamespace(paused=False)
    )
    om = OrderManager(ctx, _RESTStub())  # type: ignore
    # place two orders
    cid1 = await om.place_order("BTCUSDT", "Buy", "Limit", qty=0.001, price=30000.0)
    cid2 = await om.place_order("BTCUSDT", "Sell", "Limit", qty=0.001, price=31000.0)
    assert cid1 and cid2
    # pause and cancel all
    ctx.guard.paused = True
    count = await om.cancel_all_for_symbol("BTCUSDT")
    assert count >= 2
    # ensure no active orders remain
    assert len(om.get_active_orders("BTCUSDT")) == 0


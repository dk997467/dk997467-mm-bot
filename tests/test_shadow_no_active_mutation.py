import asyncio
from types import SimpleNamespace
from src.execution.order_manager import OrderManager


class _REST:
    async def place_order(self, **kw): return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "x"}}
    def _round_to_tick(self, p, s): return p
    def _round_to_lot(self, q, s): return q


def test_shadow_no_active_mutation():
    cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                          trading=SimpleNamespace(symbols=["BTCUSDT"]),
                          shadow=SimpleNamespace(enabled=True))
    ctx = SimpleNamespace(cfg=cfg, metrics=None)
    om = OrderManager(ctx, _REST())  # type: ignore

    async def run():
        before = dict(om.active_orders)
        cid = await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        after = dict(om.active_orders)
        assert before == after
        assert cid.startswith("shadow:")
    asyncio.run(run())


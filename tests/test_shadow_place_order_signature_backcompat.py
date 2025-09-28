import asyncio
from types import SimpleNamespace
from src.execution.order_manager import OrderManager


class _REST:
    async def place_order(self, **kw): return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "x"}}
    def _round_to_tick(self, p, s): return p
    def _round_to_lot(self, q, s): return q


def test_shadow_place_order_signature_backcompat():
    cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                          trading=SimpleNamespace(symbols=["BTCUSDT"]),
                          shadow=SimpleNamespace(enabled=True))
    ctx = SimpleNamespace(cfg=cfg, metrics=None)
    om = OrderManager(ctx, _REST())  # type: ignore

    async def run():
        c1 = await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0, cid="X1")
        c2 = await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0, client_order_id="X1")
        assert c1 == "shadow:X1" and c2 == "shadow:X1"
    asyncio.run(run())



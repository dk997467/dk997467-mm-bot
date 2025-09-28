import asyncio
from types import SimpleNamespace
from src.execution.order_manager import OrderManager


class _RESTCounting:
    def __init__(self):
        self.calls = 0
    async def place_order(self, **kw):
        self.calls += 1
        return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "x"}}
    def _round_to_tick(self, p, s): return p
    def _round_to_lot(self, q, s): return q


def test_shadow_no_rest_calls():
    cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                          trading=SimpleNamespace(symbols=["BTCUSDT"]),
                          shadow=SimpleNamespace(enabled=True))
    ctx = SimpleNamespace(cfg=cfg, metrics=None)
    rest = _RESTCounting()
    om = OrderManager(ctx, rest)  # type: ignore

    async def run():
        cid = await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        assert cid.startswith("shadow:")
        assert rest.calls == 0
    asyncio.run(run())


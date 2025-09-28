import asyncio
from types import SimpleNamespace
from src.execution.order_manager import OrderManager


class _RESTStub:
    def __init__(self):
        self._pages = [
            {
                "result": {
                    "list": [
                        {"symbol": "BTCUSDT", "side": "Buy", "orderLinkId": "c1", "orderId": "1", "price": "50000", "qty": "0.002", "cumExecQty": "0", "orderStatus": "New"},
                        {"symbol": "BTCUSDT", "side": "Sell", "orderLinkId": "c2", "orderId": "2", "price": "51000", "qty": "0.001", "cumExecQty": "0", "orderStatus": "New"},
                    ]
                }
            },
            {
                "result": {
                    "list": [
                        {"symbol": "ETHUSDT", "side": "Buy", "orderLinkId": "c3", "orderId": "3", "price": "3000", "qty": "0.1", "cumExecQty": "0", "orderStatus": "New"},
                    ]
                }
            }
        ]
        self._i = 0

    async def get_active_orders(self, symbol=None):
        if self._i >= len(self._pages):
            return {"result": {"list": []}}
        p = self._pages[self._i]
        self._i += 1
        return p


def test_sync_open_orders_and_metrics():
    ctx = SimpleNamespace(cfg=SimpleNamespace(
        trading=SimpleNamespace(symbols=["BTCUSDT", "ETHUSDT"]),
        strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0)
    ), metrics=None)
    rest = _RESTStub()
    om = OrderManager(ctx, rest)  # type: ignore

    async def run():
        n1 = await om.sync_open_orders()
        n2 = await om.sync_open_orders()
        assert (n1 + n2) >= 3
        assert "c1" in om.active_orders and "c3" in om.active_orders
        # snapshot cycle
        ok = om.save_orders_snapshot("artifacts/test_orders_snapshot.json")
        assert ok is True
        om.active_orders.clear()
        loaded = om.load_orders_snapshot("artifacts/test_orders_snapshot.json")
        assert loaded >= 3 and "c1" in om.active_orders
    asyncio.run(run())


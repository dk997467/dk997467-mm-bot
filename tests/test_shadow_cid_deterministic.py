import asyncio
from types import SimpleNamespace
from src.execution.order_manager import OrderManager


class _REST:
    async def place_order(self, **kw): return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "x"}}
    def _round_to_tick(self, p, s): return p
    def _round_to_lot(self, q, s): return q


def test_shadow_cid_deterministic():
    cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                          trading=SimpleNamespace(symbols=["BTCUSDT"]),
                          shadow=SimpleNamespace(enabled=True))
    ctx = SimpleNamespace(cfg=cfg, metrics=None)
    om = OrderManager(ctx, _REST())  # type: ignore

    async def run():
        cid1 = await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        cid2 = await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        # deterministic hashed cids
        assert cid1.startswith("shadow:h") and cid2.startswith("shadow:h")
        assert cid1 == cid2
    asyncio.run(run())


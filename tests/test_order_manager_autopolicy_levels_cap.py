import asyncio
from types import SimpleNamespace
from src.execution.order_manager import OrderManager


class _RESTStub:
    async def place_order(self, **kwargs):
        return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "cid"}}
    def _round_to_tick(self, price, symbol):
        return price
    def _round_to_lot(self, qty, symbol):
        return qty


def test_autopolicy_levels_cap_blocks_third():
    # ctx with autopolicy overrides
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(strategy=SimpleNamespace(
            amend_price_threshold_bps=10,
            amend_size_threshold=0.1,
            min_time_in_book_ms=0
        )),
        portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100000.0, max_levels=4)},
        autopolicy_overrides={"levels_per_side_max_eff": 2},
    )
    om = OrderManager(ctx, _RESTStub())

    async def run():
        # Place two orders on the same side
        await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        # Third should be blocked by effective cap
        try:
            await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
            assert False, "Expected cap block"
        except Exception as e:
            assert "cap reached" in str(e) or "cap" in str(e)

    asyncio.run(run())


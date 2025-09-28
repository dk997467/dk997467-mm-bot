import asyncio
from types import SimpleNamespace
from src.execution.order_manager import OrderManager
from src.guards.circuit import CircuitBreaker


class _RESTStub:
    async def place_order(self, **kwargs):
        return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "x"}, "httpCode": 200}
    async def amend_order(self, **kwargs):
        return {"retCode": 0, "result": {} , "httpCode": 200}
    def _round_to_tick(self, p, s): return p
    def _round_to_lot(self, q, s): return q


def test_order_manager_circuit_blocks_create_amend_allows_cancel():
    cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                          trading=SimpleNamespace(symbols=["BTCUSDT"]))
    ctx = SimpleNamespace(cfg=cfg, metrics=None)
    cb = CircuitBreaker(SimpleNamespace(window_sec=10.0, err_rate_open=0.0, http_5xx_rate_open=0.0, http_429_rate_open=0.0,
                                        open_duration_sec=60.0, half_open_probes=1, cooldown_sec=1.0))
    cb._state = 'open'
    ctx.circuit = cb
    om = OrderManager(ctx, _RESTStub())  # type: ignore

    async def run():
        try:
            await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
            assert False, "expected circuit_open"
        except Exception as e:
            assert 'circuit_open' in str(e)
    asyncio.run(run())


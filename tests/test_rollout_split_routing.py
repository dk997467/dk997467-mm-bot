"""
Test deterministic sticky split routing by CID.
"""
from types import SimpleNamespace


def test_rollout_split_routing_sticky_and_ratio():
    from src.execution.order_manager import OrderManager
    from src.connectors.bybit_rest import BybitRESTConnector

    class _RESTStub(BybitRESTConnector):
        def __init__(self):
            pass
        async def place_order(self, **kwargs):
            return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": kwargs.get('client_order_id','cid')}, "httpCode": 200}
        async def amend_order(self, **kwargs):
            return {"retCode": 0, "result": {}, "httpCode": 200}
        def _round_to_tick(self, p, s): return p
        def _round_to_lot(self, q, s): return q

    # rollout split 30%
    cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                          trading=SimpleNamespace(symbols=["BTCUSDT"]),
                          rollout=SimpleNamespace(traffic_split_pct=30, active="blue"))
    ctx = SimpleNamespace(cfg=cfg, metrics=SimpleNamespace(inc_rollout_order=lambda color: None))
    om = OrderManager(ctx, _RESTStub())  # type: ignore

    # Generate CIDs deterministically and test color mapping
    def color_of(cid: str) -> str:
        return om._choose_color(cid)

    green = 0
    total = 100
    for i in range(total):
        cid = f"CID-{i}"
        c = color_of(cid)
        if c == 'green':
            green += 1
        # sticky: same CID again -> same color
        assert color_of(cid) == c

    # Approximately 30% to green (exact modulo hash bucket; allow tolerance)
    ratio = green / total
    assert 0.2 <= ratio <= 0.4



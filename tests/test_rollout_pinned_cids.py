"""
Pinned CIDs always route to GREEN.
"""
from types import SimpleNamespace


def test_rollout_pinned_cids_always_green():
    from src.execution.order_manager import OrderManager
    from src.connectors.bybit_rest import BybitRESTConnector

    class _RESTStub(BybitRESTConnector):
        def __init__(self):
            pass
        async def place_order(self, **kwargs):
            return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": kwargs.get('client_order_id','')}, "httpCode": 200}
        async def amend_order(self, **kwargs):
            return {"retCode": 0, "result": {}, "httpCode": 200}
        def _round_to_tick(self, p, s): return p
        def _round_to_lot(self, q, s): return q

    cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                          trading=SimpleNamespace(symbols=["BTCUSDT"]),
                          rollout=SimpleNamespace(traffic_split_pct=0, active="blue", salt="X", pinned_cids_green=["CID-PIN"]))
    ctx = SimpleNamespace(cfg=cfg, metrics=SimpleNamespace(inc_rollout_order=lambda color: None, inc_rollout_pinned_hit=lambda: None))
    om = OrderManager(ctx, _RESTStub())  # type: ignore
    assert om._choose_color("CID-PIN") == 'green'
    assert om._choose_color("CID-OTHER") == 'blue'



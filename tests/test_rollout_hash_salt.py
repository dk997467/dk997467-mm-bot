"""
Salt affects sticky split distribution.
"""
from types import SimpleNamespace


def test_rollout_hash_salt_changes_distribution():
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

    def colors_for_salt(salt: str):
        cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                              trading=SimpleNamespace(symbols=["BTCUSDT"]),
                              rollout=SimpleNamespace(traffic_split_pct=30, active="blue", salt=salt, pinned_cids_green=[]))
        ctx = SimpleNamespace(cfg=cfg, metrics=SimpleNamespace(inc_rollout_order=lambda color: None))
        om = OrderManager(ctx, _RESTStub())  # type: ignore
        total = 500
        colors = []
        for i in range(total):
            cid = f"CID-{i}"
            colors.append(om._choose_color(cid))
        return colors

    c1 = colors_for_salt("A")
    c2 = colors_for_salt("B")
    total = len(c1)
    # Ratios near split (30%) for each salt
    r1 = sum(1 for x in c1 if x == 'green') / total
    r2 = sum(1 for x in c2 if x == 'green') / total
    assert abs(r1 - 0.30) < 0.1
    assert abs(r2 - 0.30) < 0.1
    # Different salt should change assignment for a good fraction of CIDs
    changed = sum(1 for i in range(total) if c1[i] != c2[i]) / total
    assert changed > 0.2



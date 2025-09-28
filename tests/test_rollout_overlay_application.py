"""
Overlay application per color.
"""
from types import SimpleNamespace


def test_rollout_overlay_application():
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

    # Base effective params
    base = {
        'autopolicy': {'level_max': 6},
        'levels_per_side_max': 6,
        'replace_threshold_bps': 2.0,
    }
    overlay_green = {"autopolicy.level_max": 3, "replace_threshold_bps": 3.5}
    overlay_blue = {}

    cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                          trading=SimpleNamespace(symbols=["BTCUSDT"]),
                          rollout=SimpleNamespace(traffic_split_pct=100, active="blue", salt="S", pinned_cids_green=[], blue=overlay_blue, green=overlay_green))
    ctx = SimpleNamespace(cfg=cfg, metrics=SimpleNamespace(inc_rollout_order=lambda color: None, inc_rollout_overlay_applied=lambda color: None))
    om = OrderManager(ctx, _RESTStub())  # type: ignore

    # Apply green overlay
    eff_green = om._apply_overlay(base, overlay_green)
    assert eff_green['autopolicy']['level_max'] == 3
    assert eff_green['replace_threshold_bps'] == 3.5
    # Base not mutated
    assert base['autopolicy']['level_max'] == 6
    assert base['replace_threshold_bps'] == 2.0
    # Blue overlay empty keeps base
    eff_blue = om._apply_overlay(base, overlay_blue)
    assert eff_blue['autopolicy']['level_max'] == 6
    assert eff_blue['replace_threshold_bps'] == 2.0



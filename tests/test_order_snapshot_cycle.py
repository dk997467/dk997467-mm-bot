from types import SimpleNamespace
from src.execution.order_manager import OrderManager, OrderState


def test_order_snapshot_cycle():
    ctx = SimpleNamespace(cfg=SimpleNamespace(
        trading=SimpleNamespace(symbols=["BTCUSDT"]),
        strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0)
    ), metrics=None)
    class _REST: pass
    om = OrderManager(ctx, _REST())  # type: ignore
    # prefill
    om.active_orders["x1"] = OrderState(order_id="1", client_order_id="x1", symbol="BTCUSDT", side="Buy",
                                        price=50000.0, qty=0.003, status="New", filled_qty=0.0, remaining_qty=0.003,
                                        created_time=0.0, last_update_time=0.0)
    path = "artifacts/test_order_snapshot_cycle.json"
    assert om.save_orders_snapshot(path) is True
    om.active_orders.clear()
    assert om.load_orders_snapshot(path) >= 1
    assert "x1" in om.active_orders and om.active_orders["x1"].symbol == "BTCUSDT"


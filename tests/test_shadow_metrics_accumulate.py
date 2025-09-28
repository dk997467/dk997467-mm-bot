from types import SimpleNamespace
from src.execution.order_manager import OrderManager


class _Gauge:
    def __init__(self): self.v = {}
    def labels(self, **kw):
        key = tuple(sorted(kw.items()))
        class _S:
            def __init__(self, parent, k): self.p, self.k = parent, k
            def set(self, v): self.p.v[self.k] = v
        return _S(self, key)

class _Counter:
    def __init__(self): self.v = {}
    def labels(self, **kw):
        key = tuple(sorted(kw.items()))
        class _S:
            def __init__(self, parent, k): self.p, self.k = parent, k
            def inc(self, n=1): self.p.v[self.k] = self.p.v.get(self.k, 0) + n
        return _S(self, key)


class _Metrics:
    def __init__(self):
        self.orders_active = _Gauge()
        self.shadow_orders_total = _Counter()
        self.shadow_price_diff_bps_last = _Gauge()
        self.shadow_price_diff_bps_avg = _Gauge()
        self.shadow_size_diff_pct_last = _Gauge()
        self.shadow_size_diff_pct_avg = _Gauge()


class _REST:
    async def place_order(self, **kw): return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "x"}}
    def _round_to_tick(self, p, s): return p
    def _round_to_lot(self, q, s): return q


def test_shadow_metrics_accumulate():
    metrics = _Metrics()
    cfg = SimpleNamespace(strategy=SimpleNamespace(amend_price_threshold_bps=10, amend_size_threshold=0.1, min_time_in_book_ms=0),
                          trading=SimpleNamespace(symbols=["BTCUSDT"]),
                          shadow=SimpleNamespace(enabled=True))
    ctx = SimpleNamespace(cfg=cfg, metrics=metrics)
    om = OrderManager(ctx, _REST())  # type: ignore
    import asyncio
    async def run():
        for i in range(3):
            await om.place_order("BTCUSDT", "Buy", "Limit", 0.001, 50000.0)
        # totals
        key = (("symbol","BTCUSDT"),)
        assert metrics.shadow_orders_total.v.get(key, 0) == 3
        # averages present
        assert (("symbol","BTCUSDT"),) in metrics.shadow_price_diff_bps_avg.v
    asyncio.run(run())


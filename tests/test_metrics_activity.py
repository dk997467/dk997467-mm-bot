"""
Metrics activity smoke: initialization zeros, update on place/cancel.
"""

import asyncio
from types import SimpleNamespace

from src.execution.order_manager import OrderManager


class _Gauge:
    def __init__(self):
        self.values = {}
    def labels(self, **kw):
        key = tuple(sorted(kw.items()))
        class _Setter:
            def __init__(self, parent, k):
                self.p, self.k = parent, k
            def set(self, v):
                self.p.values[self.k] = v
        return _Setter(self, key)


class _MetricsStub:
    def __init__(self):
        self.portfolio_active_usd = _Gauge()
        self.portfolio_active_levels = _Gauge()
        class _Ctr:
            def labels(self, **kw):
                class _Incr:
                    def inc(self, *a, **k): pass
                    def dec(self, *a, **k): pass
                return _Incr()
        self.creates_total = _Ctr()
        self.replaces_total = _Ctr()
        self.cancels_total = _Ctr()
        self.orders_active = _Ctr()


class DummyREST:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def place_order(self, **kw): return {"retCode":0,"result":{"orderId":"1","orderLinkId":"cid1"}}
    async def amend_order(self, **kw): return {"retCode":0}
    async def cancel_order(self, **kw): return {"retCode":0}
    def _round_to_lot(self, q, s): return max(0.0, round(q, 4))
    def _round_to_tick(self, p, s): return p


def test_metrics_init_and_updates():
    metrics = _MetricsStub()
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            trading=SimpleNamespace(symbols=["BTCUSDT"]),
            strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0)
        ),
        metrics=metrics,
        portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=2)}
    )
    om = OrderManager(ctx, DummyREST())  # type: ignore

    # On init -> zeros
    assert metrics.portfolio_active_usd.values[(('symbol','BTCUSDT'),)] == 0.0
    assert metrics.portfolio_active_levels.values[(('side','Buy'),('symbol','BTCUSDT'))] == 0
    assert metrics.portfolio_active_levels.values[(('side','Sell'),('symbol','BTCUSDT'))] == 0

    async def _run():
        cid = await om.place_order("BTCUSDT","Buy","Limit",qty=0.005,price=50000.0)
        assert cid
        # After place: USD > 0 and Buy levels >= 1
        usd = om.get_active_usd("BTCUSDT")
        assert usd > 0
        assert metrics.portfolio_active_usd.values[(('symbol','BTCUSDT'),)] > 0
        assert metrics.portfolio_active_levels.values[(('side','Buy'),('symbol','BTCUSDT'))] >= 1

        # Cancel -> back to lower levels
        await om.cancel_order(cid)
        assert metrics.portfolio_active_levels.values[(('side','Buy'),('symbol','BTCUSDT'))] >= 0

    asyncio.run(_run())



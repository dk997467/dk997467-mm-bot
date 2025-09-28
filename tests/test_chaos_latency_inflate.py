def test_chaos_latency_inflate():
    from src.execution.order_manager import OrderManager
    from types import SimpleNamespace
    class DummyRest:
        async def place_order(self, **kwargs):
            return {"retCode": 0, "retMsg": "ok", "result": {"orderId":"1","orderLinkId":"1"}}
    class Ctx:
        def __init__(self):
            self.cfg = SimpleNamespace(
                rollout=SimpleNamespace(traffic_split_pct=100, active='blue', salt='s', pinned_cids_green=[]),
                chaos=SimpleNamespace(enabled=True, reject_inflate_pct=0.0, latency_inflate_ms=100),
                strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=1.0, min_time_in_book_ms=0)
            )
            class _Lbl:
                def inc(self, *args, **kwargs):
                    return None
                def dec(self, *args, **kwargs):
                    return None
            class _Metrics:
                def __init__(self):
                    self._fills = fills
                def inc_rollout_order(self, color):
                    return None
                def inc_rollout_fill(self, color, ms):
                    self._fills.append((color, ms))
                def creates_total(self):
                    pass
                creates_total = SimpleNamespace(labels=lambda **kw: _Lbl())
                orders_active = SimpleNamespace(labels=lambda **kw: _Lbl())
            self.metrics = _Metrics()
    fills = []
    ctx = Ctx()
    om = OrderManager(SimpleNamespace(cfg=ctx.cfg, metrics=ctx.metrics), DummyRest())
    import asyncio
    asyncio.run(om.place_order("BTCUSDT","Buy","Limit",1.0,price=10000.0,cid="x"))
    # verify latency inflated for green (>=100ms)
    assert fills and fills[0][0] == 'green' and fills[0][1] >= 100.0



def test_chaos_reject_inflate():
    from src.execution.order_manager import OrderManager
    from types import SimpleNamespace
    class DummyRest:
        async def place_order(self, **kwargs):
            return {"retCode": 10001, "retMsg": "reject", "httpCode": 400}
    class Ctx:
        def __init__(self):
            self.cfg = SimpleNamespace(
                rollout=SimpleNamespace(traffic_split_pct=100, active='blue', salt='s', pinned_cids_green=[]),
                chaos=SimpleNamespace(enabled=True, reject_inflate_pct=3.0, latency_inflate_ms=0),
                strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=1.0, min_time_in_book_ms=0)
            )
            self.metrics = SimpleNamespace(
                inc_rollout_order=lambda color: None,
                inc_rollout_reject=lambda color: counts.__setitem__(color, counts.get(color, 0)+1)
            )
    counts = {}
    ctx = Ctx()
    om = OrderManager(SimpleNamespace(cfg=ctx.cfg, metrics=ctx.metrics), DummyRest())
    try:
        # choose green (100%) and cause reject; expect 1(base)+floor(3.0)=3 extra = 4 total
        import asyncio
        asyncio.run(om.place_order("BTCUSDT","Buy","Limit",1.0,price=10000.0,cid="x"))
    except Exception:
        pass
    assert counts.get('green', 0) >= 4



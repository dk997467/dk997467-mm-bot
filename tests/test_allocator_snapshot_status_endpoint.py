import asyncio
from types import SimpleNamespace


class _App:
    def __init__(self, metrics, path):
        self.metrics = metrics
        self._allocator_snapshot_path = path

    async def _admin_allocator_snapshot_status(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._admin_allocator_snapshot_status(self, req)  # type: ignore


class _Req:
    pass


class _M:
    def __init__(self):
        self.snap = {"allocator_last_write_ts": 12.0, "allocator_last_load_ts": 7.0}
    def get_portfolio_metrics_snapshot(self):
        return self.snap


def test_allocator_snapshot_status_endpoint(tmp_path):
    app = _App(metrics=_M(), path=str(tmp_path / "hwm.json"))
    async def run():
        resp = await app._admin_allocator_snapshot_status(_Req())
        assert resp.status == 200
    asyncio.run(run())



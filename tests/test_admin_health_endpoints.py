import asyncio
from types import SimpleNamespace


class _Req:
    pass


class _App:
    def __init__(self, paused=False, circuit_open=False):
        # minimal ctx and config
        guard = SimpleNamespace(paused=paused)
        self.ctx = SimpleNamespace(guard=guard, circuit=SimpleNamespace(state=lambda: ('open' if circuit_open else 'closed')))
        self.config = SimpleNamespace(runtime_guard=SimpleNamespace(dry_run=False, manual_override_pause=False))
        self._params_hash = 'abc'
        from cli.run_bot import MarketMakerBot
    async def _sre_healthz(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._sre_healthz(self, req)  # type: ignore
    async def _sre_readyz(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._sre_readyz(self, req)  # type: ignore
    async def _sre_version(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._sre_version(self, req)  # type: ignore


def test_admin_health_endpoints():
    app = _App(paused=False, circuit_open=False)
    async def run_ok():
        r1 = await app._sre_healthz(_Req())
        assert r1.status == 200
        r2 = await app._sre_readyz(_Req())
        assert r2.status == 200
        r3 = await app._sre_version(_Req())
        assert r3.status == 200
    asyncio.run(run_ok())

    app2 = _App(paused=True, circuit_open=False)
    async def run_guard():
        r = await app2._sre_readyz(_Req())
        assert r.status == 503
    asyncio.run(run_guard())

    app3 = _App(paused=False, circuit_open=True)
    async def run_circ():
        r = await app3._sre_readyz(_Req())
        assert r.status == 503
    asyncio.run(run_circ())



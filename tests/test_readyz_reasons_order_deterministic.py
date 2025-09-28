import asyncio
from types import SimpleNamespace


class _Req: pass


class _App:
    def __init__(self, paused, circ):
        self.ctx = SimpleNamespace(guard=SimpleNamespace(paused=paused), circuit=SimpleNamespace(state=lambda: circ))
        self.config = SimpleNamespace(runtime_guard=SimpleNamespace(dry_run=False, manual_override_pause=False))
    async def _sre_readyz(self, req):
        from cli.run_bot import MarketMakerBot
        return await MarketMakerBot._sre_readyz(self, req)  # type: ignore


def test_readyz_reasons_order_deterministic():
    app = _App(paused=True, circ='open')
    async def run():
        r = await app._sre_readyz(_Req())
        assert r.status == 503
        import json
        data = json.loads(r.text)
        assert data.get('reasons') == sorted(data.get('reasons'))
    asyncio.run(run())



import asyncio
from types import SimpleNamespace


class _App:
    def __init__(self, alloc):
        self.ctx = SimpleNamespace(allocator=alloc)

    async def _admin_allocator_reset_hwm(self, req):
        from cli.run_bot import MarketMakerBot  # just to ensure imports ok
        return await MarketMakerBot._admin_allocator_reset_hwm(self, req)  # type: ignore


class _Req:
    def __init__(self, body):
        self._body = body
    async def json(self):
        return self._body


def test_admin_reset_hwm_handler():
    from src.portfolio.allocator import PortfolioAllocator
    po = {
        'budget_usd': 1000.0,
        'mode': 'manual',
        'manual_weights': {},
        'min_weight': 0.0,
        'max_weight': 1.0,
        'levels_per_side_min': 1,
        'levels_per_side_max': 10,
        'rebalance_minutes': 5,
        'ema_alpha': 0.0,
        'risk_parity_max_iterations': 50,
        'risk_parity_tolerance': 1e-6,
        'vol_eps': 1e-9,
        'budget': SimpleNamespace(pnl_sensitivity=0.5, drawdown_soft_cap=0.1, budget_min_usd=0.0),
    }
    ctx = SimpleNamespace(cfg=SimpleNamespace(portfolio=SimpleNamespace(**po)), metrics=None)
    alloc = PortfolioAllocator(ctx)
    app = _App(alloc)

    async def run():
        # zero
        resp = await app._admin_allocator_reset_hwm(_Req({"mode": "zero"}))
        assert resp.status == 200
        # to_current_equity
        resp2 = await app._admin_allocator_reset_hwm(_Req({"mode": "to_current_equity", "equity_usd": 1234.5}))
        assert resp2.status == 200
    asyncio.run(run())



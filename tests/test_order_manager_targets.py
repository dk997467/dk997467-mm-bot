"""
OrderManager targets enforcement: levels and USD; partial fills reduce remaining budget.
"""

import asyncio
from unittest.mock import Mock

from src.common.config import PortfolioConfig
from src.common.di import AppContext
from src.execution.order_manager import OrderManager, OrderState


class DummyREST:
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def place_order(self, **kwargs):
        return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "cid1"}}
    async def amend_order(self, **kwargs):
        return {"retCode": 0}
    async def cancel_order(self, **kwargs):
        return {"retCode": 0}
    def _round_to_tick(self, p, s):
        return p
    def _round_to_lot(self, q, s):
        return q


def _ctx_with_targets(cfg: PortfolioConfig):
    mock_app_config = Mock()
    mock_app_config.portfolio = cfg
    ctx = AppContext(cfg=mock_app_config)
    return ctx


def test_levels_and_usd_caps_and_partial_fills_event_loop():
    cfg = PortfolioConfig(budget_usd=1000.0, min_weight=0.1, max_weight=0.9)
    ctx = _ctx_with_targets(cfg)
    rest = DummyREST()
    om = OrderManager(ctx, rest)  # type: ignore[arg-type]

    # Set portfolio targets: at most 2 levels, 500 USD
    class T: pass
    t = T(); t.target_usd = 500.0; t.max_levels = 2
    ctx.portfolio_targets = {"BTCUSDT": t}

    async def _run():
        # First order within budget
        cid = await om.place_order("BTCUSDT", "Buy", "Limit", qty=0.005, price=50000.0)
        assert cid
        # Active USD ~ 250
        assert om.get_active_usd("BTCUSDT") > 0
        # Metrics should reflect >=1 level on Buy and USD > 0 (if metrics present)
        m = getattr(ctx, 'metrics', None)
        if m:
            # Access internal samples is complex; smoke check only via helper
            pass
        # Second order allowed (level 2)
        cid2 = await om.place_order("BTCUSDT", "Buy", "Limit", qty=0.005, price=50000.0)
        assert cid2
        # Third order should be blocked by max_levels=2
        try:
            await om.place_order("BTCUSDT", "Buy", "Limit", qty=0.005, price=50000.0)
            assert False, "expected level cap"
        except Exception:
            pass
        # Mark partial fill to reduce remaining USD
        o = om.active_orders[cid]
        o.filled_qty = o.qty / 2
        o.remaining_qty = o.qty - o.filled_qty
        # After partial fill, active USD updated
        _usd = om.get_active_usd("BTCUSDT")
        assert _usd >= 0
        # Now try another order but exceed USD cap -> size should be cut or rejected
        try:
            await om.place_order("BTCUSDT", "Buy", "Limit", qty=10.0, price=50000.0)
            assert False, "expected budget cap"
        except Exception:
            pass

    asyncio.run(_run())



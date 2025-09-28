from types import SimpleNamespace
import pytest

from src.guards.runtime import RuntimeGuard
from src.common.config import RuntimeGuardConfig
from src.execution.order_manager import OrderManager


class _RESTStub:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def place_order(self, **kw):
        return {"retCode": 0, "result": {"orderId": "1", "orderLinkId": "cid"}}
    def _round_to_lot(self, q, s):
        return max(0.0, round(q, 4))
    async def cancel_order(self, **kw):
        return {"retCode": 0, "result": {}}


@pytest.mark.asyncio
async def test_dry_run_allows_place_order():
    cfg = SimpleNamespace(
        trading=SimpleNamespace(symbols=["BTCUSDT"]),
        strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0),
        runtime_guard=RuntimeGuardConfig(dry_run=True)
    )
    ctx = SimpleNamespace(cfg=cfg, metrics=None, portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=2)}, guard=RuntimeGuard(cfg.runtime_guard))
    # force paused but dry_run
    ctx.guard.paused = True
    om = OrderManager(ctx, _RESTStub())  # type: ignore
    cid = await om.place_order("BTCUSDT", "Buy", "Limit", qty=0.001, price=30000.0)
    assert cid


@pytest.mark.asyncio
async def test_manual_override_blocks():
    cfg = SimpleNamespace(
        trading=SimpleNamespace(symbols=["BTCUSDT"]),
        strategy=SimpleNamespace(amend_price_threshold_bps=1.0, amend_size_threshold=0.2, min_time_in_book_ms=0),
        runtime_guard=RuntimeGuardConfig(dry_run=False, manual_override_pause=True)
    )
    ctx = SimpleNamespace(cfg=cfg, metrics=None, portfolio_targets={"BTCUSDT": SimpleNamespace(target_usd=100.0, max_levels=2)}, guard=RuntimeGuard(cfg.runtime_guard))
    # evaluate will set manual reason
    ctx.guard.update({'cancel_rate_per_sec':0.0,'cfg_max_cancel_per_sec':1.0,'rest_error_rate':0.0,'pnl_slope_per_min':0.0}, 0.0)
    ctx.guard.paused = True
    om = OrderManager(ctx, _RESTStub())  # type: ignore
    with pytest.raises(Exception):
        await om.place_order("BTCUSDT", "Buy", "Limit", qty=0.001, price=30000.0)


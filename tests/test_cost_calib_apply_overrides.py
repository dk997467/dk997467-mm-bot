import json
from types import SimpleNamespace
from prometheus_client import REGISTRY

from src.common.config import AppConfig
from src.common.di import AppContext
from src.metrics.exporter import Metrics
from src.portfolio.allocator import PortfolioAllocator


def _reset_registry():
    try:
        for col in list(REGISTRY._collector_to_names.keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
    except Exception:
        pass


def _run_async(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_apply_overrides_affects_allocator_only_for_symbols():
    _reset_registry()
    cfg = AppConfig()
    cfg.portfolio.budget_usd = 10000.0
    cfg.portfolio.manual_weights = {"BTCUSDT": 0.5, "ETHUSDT": 0.5}
    ctx = AppContext(cfg=cfg)
    m = Metrics(ctx)
    ctx.metrics = m
    alloc = PortfolioAllocator(ctx)

    # Prepare bot stub and call real apply endpoint
    from cli.run_bot import MarketMakerBot
    bot = MarketMakerBot.__new__(MarketMakerBot)
    bot.metrics = m
    bot._check_admin_token = lambda req: True
    bot._admin_actor_hash = lambda req: "t"
    bot._admin_rate_limit_check = lambda actor, ep: True
    def mkreq(body: dict):
        async def _json():
            return body
        return SimpleNamespace(headers={"X-Admin-Token": "t"}, rel_url=SimpleNamespace(query={}), json=_json)

    res = _run_async(bot._admin_cost_calibration_apply(mkreq({"symbols": {"BTCUSDT": {"k_eff": 20.0, "cap_eff_bps": 5.0}}})))
    assert res.status == 200
    data = json.loads(res.text)
    assert data.get('status') == 'ok'
    assert 'BTCUSDT' in data.get('applied', {})

    # Baseline without overrides for ETH
    m.set_allocator_cost_inputs("BTCUSDT", spread_bps=0.0, volume_usd=1e6, slippage_bps=0.0)
    m.set_allocator_cost_inputs("ETHUSDT", spread_bps=0.0, volume_usd=1e6, slippage_bps=0.0)
    t = alloc.targets_from_weights(cfg.portfolio.manual_weights, budget_available_usd=cfg.portfolio.budget_usd)
    # BTC should be attenuated stronger due to k_eff override
    assert t["BTCUSDT"].target_usd <= t["ETHUSDT"].target_usd + 1e-6



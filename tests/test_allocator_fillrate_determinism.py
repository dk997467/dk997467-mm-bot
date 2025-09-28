from types import SimpleNamespace
from tests.e2e._utils import make_metrics_ctx
from src.portfolio.allocator import PortfolioAllocator
import json


def _mk_ctx():
    cfg = SimpleNamespace(
        portfolio=SimpleNamespace(
            budget=SimpleNamespace(budget_min_usd=0.0),
            min_weight=0.0,
            max_weight=1.0,
            levels_per_side_min=1,
            levels_per_side_max=10,
            cost=SimpleNamespace(
                fee_bps_default=0.0,
                slippage_bps_base=0.0,
                slippage_k_bps_per_kusd=0.0,
                cost_sensitivity=0.0,
                use_shadow_spread=False,
                use_shadow_volume=False,
                min_volume_usd=0.0,
                max_slippage_bps_cap=0.0,
                fill_rate_floor=0.7,
                fill_rate_sensitivity=0.5,
                fill_rate_half_life_sec=10,
                per_symbol={},
            ),
            mode="manual",
            manual_weights={"BTC": 0.5, "ETH": 0.5},
            budget_usd=10000.0,
        )
    )
    return SimpleNamespace(cfg=cfg)


def test_determinism_two_runs():
    ctx = _mk_ctx()
    metrics = make_metrics_ctx()
    ctx.metrics = metrics
    alloc = PortfolioAllocator(ctx)
    alloc.set_metrics(metrics)
    # set some fillrate
    metrics.reset_cost_fillrate_for_tests()
    for _ in range(10):
        metrics.record_fill_event('BTC', True)
        metrics.record_fill_event('ETH', True)
    w = {"BTC": 0.5, "ETH": 0.5}
    t1 = alloc.targets_from_weights(w, budget_available_usd=10000.0)
    t2 = alloc.targets_from_weights(dict(reversed(list(w.items()))), budget_available_usd=10000.0)
    s1 = json.dumps({k: v.target_usd for k, v in sorted(t1.items())}, sort_keys=True, separators=(",", ":"))
    s2 = json.dumps({k: v.target_usd for k, v in sorted(t2.items())}, sort_keys=True, separators=(",", ":"))
    assert s1 == s2



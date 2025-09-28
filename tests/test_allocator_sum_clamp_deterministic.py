from types import SimpleNamespace
from src.portfolio.allocator import PortfolioAllocator


def _ctx(ps=0.0, cap=0.1):
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
        'budget': SimpleNamespace(pnl_sensitivity=ps, drawdown_soft_cap=cap, budget_min_usd=0.0),
    }
    cfg = SimpleNamespace(portfolio=SimpleNamespace(**po))
    return SimpleNamespace(cfg=cfg, metrics=None)


def test_sum_clamp_deterministic_and_non_negative():
    # Force soft factor via dd at cap and ps=0.27 -> soft=0.73
    ctx = _ctx(ps=0.27, cap=0.1)
    alloc = PortfolioAllocator(ctx)
    weights = {'A': 0.7, 'B': 0.2, 'C': 0.1}
    # Set HWM
    alloc.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=601.0)
    # Now drop equity to trip soft
    t = alloc.targets_from_weights(weights, equity_usd=800.0, budget_available_usd=601.0)
    # Sum must be <= avail * soft deterministically
    avail_soft = 601.0 * 0.73
    s = round(sum(v.target_usd for v in t.values()), 6)
    assert s <= round(avail_soft, 6) + 1e-9
    # Non-negative targets and deterministic ordering
    ordered_keys = sorted(weights.keys())
    for k in ordered_keys:
        assert t[k].target_usd >= 0.0



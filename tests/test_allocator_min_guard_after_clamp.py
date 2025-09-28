from types import SimpleNamespace
from src.portfolio.allocator import PortfolioAllocator


def test_min_guard_applied_after_sum_clamp():
    # Setup where last symbol will be clamped below min and then zeroed
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
        'budget': SimpleNamespace(pnl_sensitivity=0.0, drawdown_soft_cap=0.1, budget_min_usd=50.0),
    }
    ctx = SimpleNamespace(cfg=SimpleNamespace(portfolio=SimpleNamespace(**po)), metrics=None)
    alloc = PortfolioAllocator(ctx)
    weights = {'A': 0.8, 'B': 0.15, 'C': 0.05}
    # No softening (pnl_sensitivity=0). Limit avail so sum clamp triggers
    t = alloc.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=601.0)
    total = round(sum(v.target_usd for v in t.values()), 6)
    assert total <= round(601.0, 6) + 1e-9
    # Last symbol alphabetically 'C' should be clamped; if drops below 50 -> zero
    assert t['C'].target_usd in (0.0, 50.0)
    assert t['A'].target_usd >= 0.0 and t['B'].target_usd >= 0.0



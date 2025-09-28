from types import SimpleNamespace
from src.portfolio.allocator import PortfolioAllocator


def test_soft_cap_zero_semantics():
    # pnl_sensitivity=0.4; soft_cap=0.0 -> if dd>0 then x=1 -> soft=0.6
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
        'budget': SimpleNamespace(pnl_sensitivity=0.4, drawdown_soft_cap=0.0, budget_min_usd=0.0),
    }
    ctx = SimpleNamespace(cfg=SimpleNamespace(portfolio=SimpleNamespace(**po)), metrics=None)
    alloc = PortfolioAllocator(ctx)
    w = {'A': 1.0}
    # set HWM
    alloc.targets_from_weights(w, equity_usd=1000.0, budget_available_usd=1000.0)
    t = alloc.targets_from_weights(w, equity_usd=900.0, budget_available_usd=1000.0)
    assert abs(t['A'].target_usd - 600.0) < 1e-9



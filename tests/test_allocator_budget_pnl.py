from types import SimpleNamespace
from src.portfolio.allocator import PortfolioAllocator


def _ctx(portfolio_overrides=None):
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
        'budget': SimpleNamespace(pnl_sensitivity=0.5, drawdown_soft_cap=0.10, budget_min_usd=0.0),
    }
    if portfolio_overrides:
        po.update(portfolio_overrides)
    cfg = SimpleNamespace(portfolio=SimpleNamespace(**po))
    return SimpleNamespace(cfg=cfg, metrics=None)


def test_budget_limits_and_soft_factor_zero_dd():
    ctx = _ctx()
    alloc = PortfolioAllocator(ctx)
    weights = {'A': 0.5, 'B': 0.5}
    # drawdown = 0 (equity == HWM); soft=1.0; avail < budget
    targets = alloc.targets_from_weights(weights, equity_usd=10000.0, budget_available_usd=600.0)
    assert targets['A'].target_usd == 300.0
    assert targets['B'].target_usd == 300.0


def test_budget_softening_dd_exceeds_soft_cap():
    ctx = _ctx()
    alloc = PortfolioAllocator(ctx)
    weights = {'A': 0.5, 'B': 0.5}
    # establish HWM
    alloc.targets_from_weights(weights, equity_usd=1000.0, budget_available_usd=1000.0)
    # now equity drops 20% -> dd=0.2; soft_cap=0.1 -> x=1 -> soft=1-0.5=0.5
    t = alloc.targets_from_weights(weights, equity_usd=800.0, budget_available_usd=600.0)
    assert abs(t['A'].target_usd - 150.0) < 1e-9
    assert abs(t['B'].target_usd - 150.0) < 1e-9


